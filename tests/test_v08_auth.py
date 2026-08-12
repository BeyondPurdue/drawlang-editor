"""v0.8.0 — user auth, per-user isolation, demo reset.

These tests DO NOT rely on the DRAWLANG_TEST_BYPASS_AUTH switch. They
exercise the real auth flow end-to-end: register, approve, login,
logout, /me, and per-user isolation on canvases/frames/library.

Because the switch is set by conftest.py at import time, we clear it
inside each test's fixture (before importing app modules).
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "editor") not in sys.path:
    sys.path.insert(0, str(_ROOT / "editor"))


# ---------------------------------------------------------------------------
# Per-test app builder (fresh temp DB, real auth, no bypass)
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_auth_app(monkeypatch):
    """Build a fresh FastAPI app with real auth, a fresh temp DB,
    and known admin/auto-approve settings."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    monkeypatch.setenv("DRAWLANG_DB_PATH", str(db_path))
    monkeypatch.setenv("DRAWLANG_ADMIN_EMAIL", "petr@bohemiamarket.com")
    monkeypatch.setenv("DRAWLANG_ADMIN_PASSWORD", "test-admin-pw")
    monkeypatch.setenv("DRAWLANG_AUTO_APPROVE_DOMAINS", "bohemiamarket.com,bmglobal.io")
    monkeypatch.delenv("DRAWLANG_TEST_BYPASS_AUTH", raising=False)

    # Force a clean module state so a new app boots against the fresh DB.
    for mod in [
        m for m in list(sys.modules)
        if m.startswith("app.") or m == "app"
    ]:
        del sys.modules[mod]

    from app import main as _main  # noqa: WPS433

    # __Host- cookies mandate Secure; TestClient must speak https for the
    # cookie jar to retain them across requests.
    with TestClient(_main.app, base_url="https://testserver") as client:
        yield client, _main


def _user_from_response(body: dict) -> dict:
    """Return the ``user`` sub-object from a login/register/me response."""
    return body["user"] if "user" in body else body


# ---------------------------------------------------------------------------
# Public/anon behaviour
# ---------------------------------------------------------------------------


def test_health_is_public(real_auth_app):
    client, _ = real_auth_app
    r = client.get("/health")
    assert r.status_code == 200


def test_api_canvases_requires_auth(real_auth_app):
    client, _ = real_auth_app
    r = client.get("/api/canvases")
    assert r.status_code == 401


def test_legacy_save_redirects_when_unauthenticated(real_auth_app):
    client, _ = real_auth_app
    r = client.post("/save", json={"name": "x", "program": ""}, follow_redirects=False)
    # Middleware redirects HTML routes; POST /save is not under /api/.
    assert r.status_code in (302, 303, 401)


def test_legacy_drawings_list_redirects_when_unauthenticated(real_auth_app):
    client, _ = real_auth_app
    r = client.get("/drawings", follow_redirects=False)
    assert r.status_code in (302, 303, 401)


# ---------------------------------------------------------------------------
# Demo user
# ---------------------------------------------------------------------------


def test_demo_user_can_login(real_auth_app):
    client, _ = real_auth_app
    r = client.post("/api/auth/login", json={"email": "demo", "password": "demo"})
    assert r.status_code == 200
    assert "__Host-drawlang" in r.headers.get("set-cookie", "")


def test_me_reflects_logged_in_demo(real_auth_app):
    client, _ = real_auth_app
    client.post("/api/auth/login", json={"email": "demo", "password": "demo"})
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    user = _user_from_response(body)
    assert user["email"] == "demo"
    assert user["role"] == "demo"


def test_logout_clears_cookie(real_auth_app):
    client, _ = real_auth_app
    client.post("/api/auth/login", json={"email": "demo", "password": "demo"})
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    me = client.get("/api/auth/me")
    # Either the endpoint returns 200 with user=None, or 401.
    assert me.status_code in (200, 401)
    if me.status_code == 200:
        body = me.json()
        assert body.get("user") in (None, {}) or body.get("ok") is False


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


def test_admin_can_login(real_auth_app):
    client, _ = real_auth_app
    r = client.post(
        "/api/auth/login",
        json={"email": "petr@bohemiamarket.com", "password": "test-admin-pw"},
    )
    assert r.status_code == 200


def test_admin_sees_admin_role_on_me(real_auth_app):
    client, _ = real_auth_app
    client.post(
        "/api/auth/login",
        json={"email": "petr@bohemiamarket.com", "password": "test-admin-pw"},
    )
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    user = _user_from_response(r.json())
    assert user["role"] == "admin"


def test_admin_endpoint_forbidden_for_demo(real_auth_app):
    client, _ = real_auth_app
    client.post("/api/auth/login", json={"email": "demo", "password": "demo"})
    r = client.get("/api/admin/users")
    assert r.status_code in (401, 403)


def test_admin_endpoint_returns_users_for_admin(real_auth_app):
    client, _ = real_auth_app
    client.post(
        "/api/auth/login",
        json={"email": "petr@bohemiamarket.com", "password": "test-admin-pw"},
    )
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    body = r.json()
    users = body["users"] if isinstance(body, dict) else body
    assert isinstance(users, list)
    emails = {u["email"] for u in users}
    assert "petr@bohemiamarket.com" in emails


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------


def test_register_bohemiamarket_email_is_auto_approved(real_auth_app):
    client, _ = real_auth_app
    r = client.post(
        "/api/auth/register",
        json={
            "email": "alice@bohemiamarket.com",
            "display_name": "Alice",
            "password": "abcd1234",
            "reason": "team member",
        },
    )
    assert r.status_code == 200
    user = _user_from_response(r.json())
    assert user["status"] == "active"
    login = client.post(
        "/api/auth/login",
        json={"email": "alice@bohemiamarket.com", "password": "abcd1234"},
    )
    assert login.status_code == 200


def test_register_external_domain_is_pending(real_auth_app):
    client, _ = real_auth_app
    r = client.post(
        "/api/auth/register",
        json={
            "email": "bob@example.org",
            "display_name": "Bob",
            "password": "abcd1234",
            "reason": "external tester",
        },
    )
    assert r.status_code == 200
    user = _user_from_response(r.json())
    assert user["status"] == "pending"
    login = client.post(
        "/api/auth/login",
        json={"email": "bob@example.org", "password": "abcd1234"},
    )
    assert login.status_code in (401, 403)


def test_admin_approve_activates_pending_user(real_auth_app):
    client, _ = real_auth_app
    client.post(
        "/api/auth/register",
        json={
            "email": "bob@example.org",
            "display_name": "Bob",
            "password": "abcd1234",
            "reason": "external tester",
        },
    )
    client.post(
        "/api/auth/login",
        json={"email": "petr@bohemiamarket.com", "password": "test-admin-pw"},
    )
    r = client.get("/api/admin/users?status=pending")
    assert r.status_code == 200
    body = r.json()
    users = body["users"] if isinstance(body, dict) else body
    bob_row = next(u for u in users if u["email"] == "bob@example.org")

    r = client.post(f"/api/admin/users/{bob_row['id']}/approve")
    assert r.status_code == 200

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"email": "bob@example.org", "password": "abcd1234"},
    )
    assert login.status_code == 200


# ---------------------------------------------------------------------------
# Per-user isolation on canvases
# ---------------------------------------------------------------------------


def _register_and_login(client, email, password="abcd1234"):
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": password,
            "reason": "test",
        },
    )
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _create_canvas(client, name: str) -> dict:
    r = client.post("/api/canvases", json={"name": name, "program": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    # Endpoint may return the canvas dict directly or under a key.
    if "canvas" in body:
        return body["canvas"]
    if "id" in body or "slug" in body:
        return body
    raise AssertionError(f"unexpected canvas response: {body!r}")


def test_users_cannot_see_each_others_canvases(real_auth_app):
    client, _ = real_auth_app

    _register_and_login(client, "alice@bohemiamarket.com")
    alice_canvas = _create_canvas(client, "Alice Canvas")
    alice_slug = alice_canvas["slug"]

    r = client.get("/api/canvases")
    assert any(c["slug"] == alice_slug for c in r.json()["canvases"])

    client.post("/api/auth/logout")
    _register_and_login(client, "carol@bmglobal.io")
    r = client.get("/api/canvases")
    slugs = [c["slug"] for c in r.json()["canvases"]]
    assert alice_slug not in slugs


def test_users_get_404_on_other_users_canvases(real_auth_app):
    client, _ = real_auth_app

    _register_and_login(client, "alice@bohemiamarket.com")
    alice = _create_canvas(client, "Secret")
    alice_slug = alice["slug"]

    client.post("/api/auth/logout")
    _register_and_login(client, "carol@bmglobal.io")
    r = client.get(f"/api/canvases/{alice_slug}")
    assert r.status_code == 404
    r = client.delete(f"/api/canvases/{alice_slug}")
    assert r.status_code == 404


def test_admin_can_see_all_canvases(real_auth_app):
    client, _ = real_auth_app

    _register_and_login(client, "alice@bohemiamarket.com")
    alice = _create_canvas(client, "Alice Public")
    alice_slug = alice["slug"]

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "petr@bohemiamarket.com", "password": "test-admin-pw"},
    )
    r = client.get("/api/canvases")
    slugs = [c["slug"] for c in r.json()["canvases"]]
    assert alice_slug in slugs


def test_owner_can_delete_own_canvas(real_auth_app):
    client, _ = real_auth_app
    _register_and_login(client, "alice@bohemiamarket.com")
    c = _create_canvas(client, "Trash Me")
    r = client.delete(f"/api/canvases/{c['slug']}")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Session cookie hardening
# ---------------------------------------------------------------------------


def test_session_cookie_uses_host_prefix(real_auth_app):
    client, _ = real_auth_app
    r = client.post("/api/auth/login", json={"email": "demo", "password": "demo"})
    cookie_header = r.headers.get("set-cookie", "")
    assert "__Host-drawlang" in cookie_header
    assert "path=/" in cookie_header.lower()
