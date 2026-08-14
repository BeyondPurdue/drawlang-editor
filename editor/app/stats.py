"""
Access statistics for the DrawLang editor.

KISS design:
  - One SQLite table ``visits`` in the same DB the auth module uses.
  - One insert per non-static page hit, done fire-and-forget from a
    FastAPI middleware. If it fails, we swallow the error — never break the
    request path.
  - Read queries all filter by the admin's chosen window and are
    aggregated at query time. No pre-computed rollups yet: at hundreds of
    visits/day this is fast enough for many years.

The ``session_key`` is derived deterministically from the request's session
cookie if the visitor is logged in, or from a hash of IP + User-Agent
otherwise. That way a single anonymous browser session counts as one
"visitor" without our storing any personal data.
"""

from __future__ import annotations

import hashlib
import socket
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from app import auth as _auth


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS visits (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT    NOT NULL,
        session_key  TEXT    NOT NULL,
        path         TEXT    NOT NULL,
        method       TEXT    NOT NULL,
        status       INTEGER NOT NULL,
        referrer     TEXT,
        ua           TEXT,
        user_id      INTEGER,
        ip_prefix    TEXT,
        country      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_visits_ts       ON visits(ts)",
    "CREATE INDEX IF NOT EXISTS idx_visits_path     ON visits(path)",
    "CREATE INDEX IF NOT EXISTS idx_visits_session  ON visits(session_key)",
    "CREATE INDEX IF NOT EXISTS idx_visits_country  ON visits(country)",
]

_write_lock = threading.Lock()


def init() -> None:
    """Create the ``visits`` table if missing. Idempotent."""
    c = _auth._conn()
    for stmt in _DDL_STATEMENTS:
        c.execute(stmt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ip_prefix(ip: str | None) -> str | None:
    """Return a network prefix hiding the last octet (IPv4) or last 80 bits (IPv6)."""
    if not ip:
        return None
    if ":" in ip:  # IPv6
        parts = ip.split(":")
        return ":".join(parts[:3]) + "::/48"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return None


def _session_key(*, session_cookie: str | None, ip: str | None, ua: str | None) -> str:
    """Stable per-visitor key. Uses session cookie if present, else IP+UA hash."""
    if session_cookie:
        raw = f"c:{session_cookie}"
    else:
        raw = f"a:{ip or '-'}|{ua or '-'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _country_from_ip(ip: str | None) -> str | None:
    """
    Best-effort country lookup via reverse DNS TLD.
    Zero external dependencies. Returns None if no signal.
    Real GeoIP is future work: swap in geoip2 + a MaxMind DB later.
    """
    if not ip:
        return None
    try:
        # Very short timeout — never block the request.
        socket.setdefaulttimeout(0.3)
        host, _, _ = socket.gethostbyaddr(ip)
    except (OSError, socket.herror, socket.timeout):
        return None
    finally:
        socket.setdefaulttimeout(None)
    if not host:
        return None
    # Take the TLD — this misses .com/.net/.org (majority of the internet),
    # but catches many national ISPs (.de, .pl, .cz, .es, .fr, .om, .ae...).
    tld = host.rsplit(".", 1)[-1].lower()
    if len(tld) == 2:
        return tld.upper()
    return None


def _client_ip(request) -> str | None:
    # Prefer X-Forwarded-For (Caddy sets this) but only trust the first hop.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real
    return request.client.host if request.client else None


# Paths we don't want to log as "page views" — static assets, health, auth churn.
_SKIP_PREFIXES = (
    "/static/",
    "/favicon",
    "/health",
    "/api/",       # API calls aren't page views
)


def should_log(path: str, method: str) -> bool:
    if method != "GET":
        return False
    for pref in _SKIP_PREFIXES:
        if path.startswith(pref):
            return False
    return True


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def log_visit(
    *,
    path: str,
    method: str,
    status: int,
    referrer: str | None,
    ua: str | None,
    session_cookie: str | None,
    ip: str | None,
    user_id: int | None,
) -> None:
    """Best-effort insert. Never raises."""
    try:
        key = _session_key(session_cookie=session_cookie, ip=ip, ua=ua)
        prefix = _ip_prefix(ip)
        country = _country_from_ip(ip)
        with _write_lock:
            c = _auth._conn()
            c.execute(
                "INSERT INTO visits (ts, session_key, path, method, status, "
                "referrer, ua, user_id, ip_prefix, country) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now_iso(),
                    key,
                    path[:512],
                    method,
                    int(status),
                    (referrer or "")[:512] or None,
                    (ua or "")[:512] or None,
                    user_id,
                    prefix,
                    country,
                ),
            )
    except Exception:
        # Never break the request path over analytics.
        pass


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def summary() -> dict[str, Any]:
    """Top-level counters."""
    c = _auth._conn()
    total_views = c.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    total_sessions = c.execute("SELECT COUNT(DISTINCT session_key) FROM visits").fetchone()[0]

    row = c.execute(
        "SELECT COUNT(*), COUNT(DISTINCT session_key) FROM visits "
        "WHERE ts >= datetime('now', '-1 day')"
    ).fetchone()
    views_24h, sessions_24h = row[0], row[1]

    row = c.execute(
        "SELECT COUNT(*), COUNT(DISTINCT session_key) FROM visits "
        "WHERE ts >= datetime('now', '-7 days')"
    ).fetchone()
    views_7d, sessions_7d = row[0], row[1]

    return {
        "total_views": total_views,
        "total_sessions": total_sessions,
        "views_24h": views_24h,
        "sessions_24h": sessions_24h,
        "views_7d": views_7d,
        "sessions_7d": sessions_7d,
    }


def by_day(days: int = 30) -> list[dict[str, Any]]:
    """Per-day visits + sessions for the last ``days`` days."""
    days = max(1, min(int(days), 3650))
    cur = _auth._conn().execute(
        "SELECT substr(ts,1,10) AS day, "
        "       COUNT(*) AS views, "
        "       COUNT(DISTINCT session_key) AS sessions "
        "FROM visits "
        "WHERE ts >= datetime('now', ?) "
        "GROUP BY day ORDER BY day",
        (f"-{days} days",),
    )
    return _rows(cur)


def top_pages(limit: int = 20) -> list[dict[str, Any]]:
    cur = _auth._conn().execute(
        "SELECT path, COUNT(*) AS views, "
        "       COUNT(DISTINCT session_key) AS sessions "
        "FROM visits GROUP BY path "
        "ORDER BY views DESC LIMIT ?",
        (int(limit),),
    )
    return _rows(cur)


def _norm_referrer(ref: str | None) -> str:
    if not ref:
        return "(direct)"
    # Strip scheme and path — keep host only, that's the signal.
    r = ref.split("://", 1)[-1]
    host = r.split("/", 1)[0].lower()
    return host or "(direct)"


def top_referrers(limit: int = 20) -> list[dict[str, Any]]:
    cur = _auth._conn().execute(
        "SELECT referrer, COUNT(*) AS views, "
        "       COUNT(DISTINCT session_key) AS sessions "
        "FROM visits GROUP BY referrer"
    )
    raw = _rows(cur)

    grouped: dict[str, dict[str, int]] = {}
    for r in raw:
        host = _norm_referrer(r["referrer"])
        g = grouped.setdefault(host, {"views": 0, "sessions": 0})
        g["views"] += r["views"]
        g["sessions"] += r["sessions"]

    out = [{"host": h, **v} for h, v in grouped.items()]
    out.sort(key=lambda r: r["views"], reverse=True)
    return out[:limit]


def by_country(limit: int = 30) -> list[dict[str, Any]]:
    cur = _auth._conn().execute(
        "SELECT COALESCE(country, '??') AS country, "
        "       COUNT(*) AS views, "
        "       COUNT(DISTINCT session_key) AS sessions "
        "FROM visits GROUP BY country "
        "ORDER BY views DESC LIMIT ?",
        (int(limit),),
    )
    return _rows(cur)


def recent(limit: int = 100) -> list[dict[str, Any]]:
    cur = _auth._conn().execute(
        "SELECT v.ts, v.path, v.method, v.status, v.referrer, "
        "       v.ua, v.ip_prefix, v.country, u.email AS user_email "
        "FROM visits v LEFT JOIN users u ON u.id = v.user_id "
        "ORDER BY v.id DESC LIMIT ?",
        (int(limit),),
    )
    return _rows(cur)
