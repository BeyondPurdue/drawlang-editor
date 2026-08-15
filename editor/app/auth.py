"""
v0.8 — User accounts, sessions, and ownership.

Design goals (KISS):

- Stdlib only. Password hashing via ``hashlib.scrypt`` (no bcrypt build).
- SQLite for users + sessions, same DB as everything else.
- HttpOnly, SameSite=Lax cookie carrying an opaque session token.
- Three roles: ``demo``, ``user``, ``admin``.
- Auto-approve any email whose domain is in ``AUTO_APPROVE_DOMAINS``.
- Middleware sets ``request.state.user`` on every request; the API deps
  translate that into ``require_user`` / ``require_admin``.

Everything a "user" owns lives in tables carrying an ``owner_id`` column.
On login as the demo user, that column is set to the demo user's id.
A nightly reset (see ``demo_reset.py``) wipes everything owned by demo.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Any

from . import storage as _storage


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    NOT NULL UNIQUE,
    display_name   TEXT    NOT NULL,
    password_hash  TEXT    NOT NULL,
    role           TEXT    NOT NULL DEFAULT 'user',   -- 'demo' | 'user' | 'admin'
    status         TEXT    NOT NULL DEFAULT 'pending',-- 'pending' | 'active' | 'disabled'
    reason         TEXT    NOT NULL DEFAULT '',       -- why they want access
    created_at     REAL    NOT NULL,
    updated_at     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Domains whose registrations become 'active' immediately. Others go into
# a 'pending' queue that the admin approves via /admin/users.
AUTO_APPROVE_DOMAINS = {
    d.strip().lower()
    for d in os.environ.get(
        "DRAWLANG_AUTO_APPROVE_DOMAINS",
        "bohemiamarket.com,bmglobal.io",
    ).split(",")
    if d.strip()
}

# The initial admin. Created on first startup if no admin exists yet.
INITIAL_ADMIN_EMAIL = os.environ.get(
    "DRAWLANG_ADMIN_EMAIL", "petr@bohemiamarket.com"
)
# Public alias for the seeded admin address. Used by the API to look up
# the admin user id so admin-owned frames/library items can be shared.
ADMIN_EMAIL = INITIAL_ADMIN_EMAIL

# Additional admins. Idempotently promoted to role='admin', status='active'
# on every startup. Users must already exist (created via /register); this
# only elevates their role.
EXTRA_ADMIN_EMAILS: tuple[str, ...] = tuple(
    e.strip() for e in os.environ.get(
        "DRAWLANG_EXTRA_ADMINS",
        "roupec@bohemiamarket.com",
    ).split(",") if e.strip()
)
INITIAL_ADMIN_PASSWORD = os.environ.get(
    "DRAWLANG_ADMIN_PASSWORD", "changeme-please"
)

# The demo user. Fixed credentials shown on the login page.
DEMO_EMAIL = "demo"
DEMO_PASSWORD = "demo"
DEMO_DISPLAY = "Demo user"

# The demo *source* user. This is a real, editable account. Every night
# the demo user is wiped and reseeded from this account's canvases, so
# whatever we curate here becomes the demo tour. Editing this account
# is the only supported way to change the demo content.
DEMO_SOURCE_EMAIL = os.environ.get(
    "DRAWLANG_DEMO_SOURCE_EMAIL", "drawlang@bohemiamarket.com"
)
DEMO_SOURCE_DISPLAY = "Demo source"
# Password is only used if the account has to be created on first boot.
# Change it after first login. Not shown anywhere in the UI.
DEMO_SOURCE_PASSWORD = os.environ.get(
    "DRAWLANG_DEMO_SOURCE_PASSWORD", "changeme-please"
)

# Cookie lifetime.
SESSION_TTL_SECONDS = 30 * 24 * 3600

# Cookie name — the `__Host-` prefix is required by our published-site
# proxy; harmless in dev too.
COOKIE_NAME = "__Host-drawlang"


_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    return _storage._connect()


# ---------------------------------------------------------------------------
# Password hashing (stdlib scrypt)
# ---------------------------------------------------------------------------

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        pw.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        salt = _unb64(salt_b64)
        expected = _unb64(dk_b64)
        got = hashlib.scrypt(
            pw.encode("utf-8"), salt=salt,
            n=n, r=r, p=p, dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return secrets.compare_digest(got, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Init + seed
# ---------------------------------------------------------------------------

def init() -> None:
    with _lock:
        _conn().executescript(SCHEMA)
    _seed_admin_and_demo()


def _seed_admin_and_demo() -> None:
    now = time.time()
    with _lock:
        c = _conn()
        # Demo user — always id 1 if we can help it; on first run fine.
        row = c.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users (email, display_name, password_hash, role, status, "
                "reason, created_at, updated_at) VALUES (?, ?, ?, 'demo', 'active', '', ?, ?)",
                (DEMO_EMAIL, DEMO_DISPLAY, hash_password(DEMO_PASSWORD), now, now),
            )
        # Demo *source* user — a real editable account whose canvases are
        # copied into `demo` every midnight. Role='user', status='active'
        # so the admin can sign in as this account, curate the showcase,
        # and let the nightly job pick up the changes.
        row = c.execute(
            "SELECT id FROM users WHERE email = ?", (DEMO_SOURCE_EMAIL,)
        ).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users (email, display_name, password_hash, role, status, "
                "reason, created_at, updated_at) VALUES (?, ?, ?, 'user', 'active', '', ?, ?)",
                (
                    DEMO_SOURCE_EMAIL, DEMO_SOURCE_DISPLAY,
                    hash_password(DEMO_SOURCE_PASSWORD), now, now,
                ),
            )
        # Admin
        row = c.execute(
            "SELECT id FROM users WHERE email = ?", (INITIAL_ADMIN_EMAIL,)
        ).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users (email, display_name, password_hash, role, status, "
                "reason, created_at, updated_at) VALUES (?, ?, ?, 'admin', 'active', '', ?, ?)",
                (
                    INITIAL_ADMIN_EMAIL, "Admin",
                    hash_password(INITIAL_ADMIN_PASSWORD), now, now,
                ),
            )
        # Promote any pre-existing users listed in EXTRA_ADMIN_EMAILS.
        for email in EXTRA_ADMIN_EMAILS:
            row = c.execute(
                "SELECT id, role, status FROM users WHERE email = ?", (email,)
            ).fetchone()
            if row is None:
                continue
            uid, role, status = row[0], row[1], row[2]
            if role != "admin" or status != "active":
                c.execute(
                    "UPDATE users SET role = 'admin', status = 'active', "
                    "updated_at = ? WHERE id = ?",
                    (now, uid),
                )
        c.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _row_to_user(row: sqlite3.Row | tuple | None) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        row = dict(row)
    else:
        row = {
            "id": row[0], "email": row[1], "display_name": row[2],
            "password_hash": row[3], "role": row[4], "status": row[5],
            "reason": row[6], "created_at": row[7], "updated_at": row[8],
        }
    row.pop("password_hash", None)
    return row


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT id, email, display_name, password_hash, role, status, reason, "
        "created_at, updated_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return _row_to_user(row)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    row = _conn().execute(
        "SELECT id, email, display_name, password_hash, role, status, reason, "
        "created_at, updated_at FROM users WHERE email = ?",
        (email.lower().strip() if "@" in email else email.strip(),),
    ).fetchone()
    return _row_to_user(row)


def demo_user_id() -> int:
    row = _conn().execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if row is None:
        raise RuntimeError("demo user missing — auth.init() not called?")
    return int(row[0])


def demo_source_user_id() -> int | None:
    """Return the id of the demo source account, or None if it doesn't
    exist yet. Kept nullable because a fresh deploy may not have seeded
    it yet when the reset scheduler first probes it.
    """
    row = _conn().execute(
        "SELECT id FROM users WHERE email = ?", (DEMO_SOURCE_EMAIL,)
    ).fetchone()
    return int(row[0]) if row else None


def register(email: str, display_name: str, password: str, reason: str = "") -> dict[str, Any]:
    email_norm = email.lower().strip()
    if not _EMAIL_RE.match(email_norm):
        raise ValueError("invalid email address")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if not display_name.strip():
        raise ValueError("display name required")
    domain = email_norm.rsplit("@", 1)[-1]
    status = "active" if domain in AUTO_APPROVE_DOMAINS else "pending"
    now = time.time()
    with _lock:
        c = _conn()
        try:
            cur = c.execute(
                "INSERT INTO users (email, display_name, password_hash, role, status, "
                "reason, created_at, updated_at) VALUES (?, ?, ?, 'user', ?, ?, ?, ?)",
                (email_norm, display_name.strip(), hash_password(password),
                 status, reason.strip()[:400], now, now),
            )
            c.commit()
            uid = cur.lastrowid
        except sqlite3.IntegrityError as e:
            raise ValueError("that email is already registered") from e
    return get_user_by_id(uid)


def authenticate(email_or_name: str, password: str) -> dict[str, Any] | None:
    """Return user dict on successful password check (any status). Caller
    is responsible for checking status == 'active'."""
    ident = email_or_name.strip()
    if "@" not in ident:
        ident_lookup = ident  # demo user has no '@'
    else:
        ident_lookup = ident.lower()
    row = _conn().execute(
        "SELECT id, email, display_name, password_hash, role, status, reason, "
        "created_at, updated_at FROM users WHERE email = ?",
        (ident_lookup,),
    ).fetchone()
    if row is None:
        return None
    stored_hash = row[3] if not isinstance(row, sqlite3.Row) else row["password_hash"]
    if not verify_password(password, stored_hash):
        return None
    return _row_to_user(row)


def list_pending() -> list[dict[str, Any]]:
    rows = _conn().execute(
        "SELECT id, email, display_name, password_hash, role, status, reason, "
        "created_at, updated_at FROM users WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_user(r) for r in rows]


def list_all_users() -> list[dict[str, Any]]:
    rows = _conn().execute(
        "SELECT id, email, display_name, password_hash, role, status, reason, "
        "created_at, updated_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_user(r) for r in rows]


def approve_user(user_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE users SET status = 'active', updated_at = ? WHERE id = ? AND role != 'admin'",
            (time.time(), user_id),
        )
        c.commit()


def disable_user(user_id: int) -> None:
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE users SET status = 'disabled', updated_at = ? WHERE id = ? AND role != 'admin'",
            (time.time(), user_id),
        )
        c.commit()


def delete_user(user_id: int) -> None:
    """Delete a user AND all their owned assets (canvases, frames, symbols)."""
    with _lock:
        c = _conn()
        # Ownership rows cascade-delete via foreign keys where declared;
        # explicitly clean the rest.
        c.execute("DELETE FROM canvases WHERE owner_id = ?", (user_id,))
        c.execute("DELETE FROM frames   WHERE owner_id = ?", (user_id,))
        c.execute("DELETE FROM library_items WHERE owner_id = ?", (user_id,))
        c.execute("DELETE FROM users    WHERE id = ? AND role != 'admin'", (user_id,))
        c.commit()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        c = _conn()
        c.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + SESSION_TTL_SECONDS),
        )
        c.commit()
    return token


def get_session_user(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    row = _conn().execute(
        "SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)
    ).fetchone()
    if row is None:
        return None
    user_id = int(row[0] if not isinstance(row, sqlite3.Row) else row["user_id"])
    expires = float(row[1] if not isinstance(row, sqlite3.Row) else row["expires_at"])
    if expires < time.time():
        destroy_session(token)
        return None
    return get_user_by_id(user_id)


def destroy_session(token: str) -> None:
    with _lock:
        c = _conn()
        c.execute("DELETE FROM sessions WHERE token = ?", (token,))
        c.commit()


def cleanup_expired_sessions() -> int:
    with _lock:
        c = _conn()
        cur = c.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        c.commit()
        return cur.rowcount or 0


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def _extract_token(request) -> str | None:
    # Cookie first
    t = request.cookies.get(COOKIE_NAME)
    if t:
        return t
    # Also accept Authorization: Bearer for API clients
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def current_user(request) -> dict[str, Any] | None:
    """Return the current user dict or None. Cached on request.state."""
    cached = getattr(request.state, "_user_cache", "unset")
    if cached != "unset":
        return cached
    tok = _extract_token(request)
    u = get_session_user(tok) if tok else None
    request.state._user_cache = u
    return u


def is_active(u: dict[str, Any] | None) -> bool:
    return bool(u and u.get("status") == "active")


def is_admin(u: dict[str, Any] | None) -> bool:
    return bool(u and u.get("role") == "admin" and u.get("status") == "active")


def _public_user(u: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip fields we never want to send to clients.

    Returns id + email + display_name + role + status only. Reason
    included so the admin panel can show it; not sensitive.
    """
    if u is None:
        return None
    return {
        "id": u.get("id"),
        "email": u.get("email"),
        "display_name": u.get("display_name"),
        "role": u.get("role"),
        "status": u.get("status"),
        "reason": u.get("reason") or "",
        "created_at": u.get("created_at"),
    }


__all__ = [
    "SCHEMA", "init", "hash_password", "verify_password",
    "register", "authenticate", "get_user_by_id", "get_user_by_email",
    "list_pending", "list_all_users",
    "approve_user", "disable_user", "delete_user", "demo_user_id",
    "demo_source_user_id",
    "DEMO_SOURCE_EMAIL", "DEMO_SOURCE_DISPLAY",
    "create_session", "get_session_user", "destroy_session", "cleanup_expired_sessions",
    "current_user", "is_active", "is_admin", "_public_user",
    "COOKIE_NAME", "SESSION_TTL_SECONDS",
    "DEMO_EMAIL", "DEMO_PASSWORD",
    "ADMIN_EMAIL", "AUTO_APPROVE_DOMAINS",
]
