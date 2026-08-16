"""
Demo user nightly reset (v0.8.0).

Wipes every canvas, frame, and library item owned by the demo user, then
copies content from the *demo source* account (see auth.DEMO_SOURCE_EMAIL).
The source account is a real editable account. Whatever we curate there
becomes the demo tour. This decouples "what visitors see" from the
interpreter code — no more hardcoded drawlang literals in this file.

If the source account has zero canvases (fresh deploy, or user hasn't
added any yet), we fall back to a minimal hardcoded seed so the demo
is never blank.

Runs in a background daemon thread; the schedule target is the next
midnight in Europe/Madrid.

Kept stdlib-only per the KISS rule. No apscheduler, no zoneinfo backports
- Python 3.9+ ships zoneinfo in the standard library.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import auth as _auth
from . import canvases as _canvases
from . import frames as _frames
from . import library as _library
from . import storage as _storage

log = logging.getLogger(__name__)


# Minimal Debian/slim images may ship without /usr/share/zoneinfo; if we
# cannot resolve Europe/Madrid, fall back to a fixed +01:00 offset. The
# nightly reset will drift by an hour on DST switch days, but the app
# will boot. Servers that need exact wall-clock alignment should install
# `tzdata` (Debian) or the `tzdata` pip package.
try:
    DEMO_TZ = ZoneInfo("Europe/Madrid")
except ZoneInfoNotFoundError:
    log.warning(
        "zoneinfo tzdata missing; falling back to fixed UTC+01:00 for demo reset"
    )
    DEMO_TZ = timezone(timedelta(hours=1))


# ---------------------------------------------------------------------------
# Fallback seed programs
# ---------------------------------------------------------------------------
# Used only when the demo source account has no canvases of its own. On
# a normal deploy the source account is preloaded by seed_source() below,
# so these are strictly a safety net.

_FALLBACK_CANVAS_SEEDS: list[dict] = [
    {
        "name": "Demo canvas",
        "slug": "demo",
        "program": (
            "# demo canvas - welcome to the drawing language editor\n"
            "ma,100,100;\n"
            "dl,200,0;\n"
            "dl,0,-100;\n"
            "dl,-200,0;\n"
            "dl,0,100;\n"
            "ma,150,60;\n"
            "tx,S,demo user - reset nightly;\n"
        ),
    },
]


_FALLBACK_LIBRARY_SEEDS: list[dict] = [
    {
        "name": "Demo box",
        "slug": "demo-box",
        "category": "symbol",
        "description": "Simple 40x20 box used by the demo tour.",
        "program": (
            "mr,0,0;\n"
            "dl,40,0;\n"
            "dl,0,-20;\n"
            "dl,-40,0;\n"
            "dl,0,20;\n"
        ),
    },
]


# ---------------------------------------------------------------------------
# Core reset
# ---------------------------------------------------------------------------


def _delete_all_for_owner(demo_id: int) -> tuple[int, int, int]:
    """Delete every canvas / frame / library item owned by demo. Returns
    (canvases, frames, library) counts. Statements cascade via foreign key.
    """
    with _canvases._lock:  # canvases module owns the connection
        c = _canvases._conn()
        n_canvases = c.execute(
            "SELECT COUNT(*) FROM canvases WHERE owner_id = ?", (demo_id,)
        ).fetchone()[0]
        c.execute("DELETE FROM canvases WHERE owner_id = ?", (demo_id,))
        n_frames = c.execute(
            "SELECT COUNT(*) FROM frames WHERE owner_id = ?", (demo_id,)
        ).fetchone()[0]
        c.execute("DELETE FROM frames WHERE owner_id = ?", (demo_id,))
        n_library = c.execute(
            "SELECT COUNT(*) FROM library_items WHERE owner_id = ?", (demo_id,)
        ).fetchone()[0]
        c.execute("DELETE FROM library_items WHERE owner_id = ?", (demo_id,))
    return n_canvases, n_frames, n_library


def _copy_source_to_demo(source_id: int, demo_id: int) -> tuple[int, int, int]:
    """Copy every canvas, frame, and library item owned by source_id into demo_id.

    Returns (n_canvases_copied, n_frames_copied, n_library_copied). Preserves
    canvas slug/name and frame binding via _canvases.copy_canvas, which does
    the deep clone (canvas + statements + field_values). Never raises;
    per-item errors are logged and skipped.

    Frames are copied FIRST so that canvases (which reference frames by id)
    can find them when they get copied. The copy uses seed_frames_for_user,
    which allocates a new unique id per frame (e.g. a3-grid -> a3-grid-2
    if the target already has an a3-grid).
    """
    n_canvases = 0
    n_frames = 0
    n_library = 0

    # Frames first — canvases may reference them.
    try:
        n_frames = _frames.seed_frames_for_user(demo_id, source_id)
    except Exception as exc:
        log.warning("demo reseed: could not copy frames from source: %s", exc)

    src_canvases = _canvases.list_canvases(owner_id=source_id)
    for row in src_canvases:
        src_id = row.get("id")
        src_slug = row.get("slug")
        src_name = row.get("name") or src_slug or "Untitled"
        if src_id is None:
            continue
        try:
            # duplicate_canvas keeps the deep-copy semantics we want
            # (canvas row + statements + field_values, no history).
            # Slugs are globally unique across the whole canvases table,
            # so we cannot reuse the source slug — the source still owns
            # it. Prefix the copy with `demo-` so it is stable, memorable,
            # and namespaced. Guard against double-prefixing on repeated
            # copies (shouldn't happen because we wipe first, but cheap).
            demo_slug = src_slug or _canvases._slug(src_name)
            if not demo_slug.startswith("demo-"):
                demo_slug = f"demo-{demo_slug}"
            _canvases.duplicate_canvas(
                src_id,
                new_slug=demo_slug,
                new_name=src_name,
                new_owner_id=demo_id,
            )
            n_canvases += 1
        except Exception as exc:
            log.warning(
                "demo reseed: failed to copy canvas %s (%s): %s",
                src_slug, src_name, exc,
            )

    # Library items: no dedicated copy helper, so read + recreate.
    try:
        src_lib = _library.list_items(owner_id=source_id)
    except TypeError:
        # Older list_items() signatures don't accept owner_id; skip lib copy.
        src_lib = []
    except Exception as exc:
        log.warning("demo reseed: could not list source library items: %s", exc)
        src_lib = []

    for item in src_lib:
        # list_items() also returns owner_id IS NULL rows (shared items)
        # — skip those; they are already visible to demo via the normal
        # shared-lookup path and we don't want double entries.
        if item.get("owner_id") != source_id:
            continue
        try:
            src_lib_slug = item.get("slug") or ""
            demo_lib_slug = src_lib_slug
            if demo_lib_slug and not demo_lib_slug.startswith("demo-"):
                demo_lib_slug = f"demo-{demo_lib_slug}"
            _library.create_item(
                name=item.get("name") or item.get("slug") or "Untitled",
                slug=demo_lib_slug or None,
                category=item.get("category", "symbol"),
                description=item.get("description", ""),
                program=item.get("program", ""),
                owner_id=demo_id,
            )
            n_library += 1
        except Exception as exc:
            log.warning(
                "demo reseed: failed to copy library item %s: %s",
                item.get("slug"), exc,
            )
    return n_canvases, n_frames, n_library


def _reseed_fallback(demo_id: int) -> None:
    """Insert the hardcoded fallback content owned by demo. Never raises.

    Only used when the source account has no canvases — a fresh deploy or
    after a database wipe, before the admin has added the showcase set.
    """
    for spec in _FALLBACK_CANVAS_SEEDS:
        try:
            _canvases.create_canvas(
                name=spec["name"],
                slug=spec.get("slug"),
                program=spec.get("program", ""),
                owner_id=demo_id,
            )
        except ValueError:
            log.info("demo reseed skipped canvas %s (slug collision)", spec["name"])
        except Exception as exc:
            log.warning("demo reseed failed for canvas %s: %s", spec["name"], exc)
    for spec in _FALLBACK_LIBRARY_SEEDS:
        try:
            _library.create_item(
                name=spec["name"],
                slug=spec.get("slug"),
                category=spec.get("category", "symbol"),
                description=spec.get("description", ""),
                program=spec.get("program", ""),
                owner_id=demo_id,
            )
        except ValueError:
            log.info("demo reseed skipped library %s (slug collision)", spec["name"])
        except Exception as exc:
            log.warning("demo reseed failed for library %s: %s", spec["name"], exc)


def _reseed(demo_id: int) -> dict:
    """Reseed the demo user. Prefer copying from the source account; if
    that account has no canvases, fall back to the hardcoded seed.

    Returns a small dict describing what happened so the /experiments/
    demo-sync page can show it.
    """
    source_id = _auth.demo_source_user_id()
    if source_id is not None:
        src_canvases = _canvases.list_canvases(owner_id=source_id)
        src_frames = _frames.list_frames_owned_by(source_id)
        if src_canvases or src_frames:
            n_c, n_f, n_l = _copy_source_to_demo(source_id, demo_id)
            log.info(
                "[demo_reset] copied from source: %s canvases, %s frames, %s library items",
                n_c, n_f, n_l,
            )
            return {
                "mode": "copy_from_source",
                "canvases_copied": n_c,
                "frames_copied": n_f,
                "library_copied": n_l,
            }
    _reseed_fallback(demo_id)
    log.info("[demo_reset] source empty or missing — used fallback seed")
    return {"mode": "fallback_seed"}


# Last reset info, exposed to /api/experiments/demo-sync for the UI.
_last_reset: dict = {
    "at": None,             # unix timestamp of last successful reset
    "mode": None,           # 'copy_from_source' | 'fallback_seed'
    "wiped": None,          # {canvases, frames, library}
    "seeded": None,         # {canvases_copied, library_copied} or {}
}


def last_reset() -> dict:
    """Return a shallow copy of the last-reset info dict."""
    return dict(_last_reset)


def reset_now() -> dict:
    """Perform one reset cycle: wipe + reseed. Returns counts wiped +
    seed mode. Updates the module-level `_last_reset` so the /experiments
    page can render "last synced at ..." without keeping its own state.
    """
    try:
        demo_id = _auth.demo_user_id()
    except Exception:
        return {"ok": False, "reason": "demo user not initialised"}
    n_c, n_f, n_l = _delete_all_for_owner(demo_id)
    seeded = _reseed(demo_id)
    log.info(
        "[demo_reset] wiped %s canvas / %s frame / %s library; reseed mode=%s",
        n_c, n_f, n_l, seeded.get("mode"),
    )
    _last_reset.update({
        "at": time.time(),
        "mode": seeded.get("mode"),
        "wiped": {"canvases": n_c, "frames": n_f, "library": n_l},
        "seeded": {k: v for k, v in seeded.items() if k != "mode"},
    })
    return {
        "ok": True,
        "canvases": n_c, "frames": n_f, "library": n_l,
        "seeded": seeded,
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def _seconds_until_next_midnight(now: datetime | None = None) -> float:
    """Seconds from ``now`` to the next Europe/Madrid midnight (00:00:00).

    ``now`` defaults to the current time in Europe/Madrid.
    """
    now = now.astimezone(DEMO_TZ) if now else datetime.now(DEMO_TZ)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max((tomorrow - now).total_seconds(), 1.0)


def _scheduler_loop(stop_event: threading.Event) -> None:
    """Sleep until midnight, reset, repeat. Never crashes the thread."""
    while not stop_event.is_set():
        try:
            wait = _seconds_until_next_midnight()
            log.info("[demo_reset] next reset in %.0fs", wait)
            # Wake up early if stop_event is set (test / shutdown path).
            if stop_event.wait(timeout=wait):
                return
            reset_now()
        except Exception as exc:
            log.exception("[demo_reset] scheduler crashed: %s", exc)
            # Back off a minute so a crash loop doesn't flatten the CPU.
            if stop_event.wait(timeout=60.0):
                return


_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start() -> None:
    """Idempotent: start the scheduler thread if it isn't already running.

    Perform an initial reset if the demo user has no seed content yet -
    for example on a fresh deploy or database wipe.
    """
    global _stop_event, _thread
    try:
        demo_id = _auth.demo_user_id()
    except Exception:
        log.warning("[demo_reset] demo user missing; skipping scheduler start")
        return

    # Perform an initial reset if there's nothing owned by demo yet, so a
    # fresh deploy still greets the user with a demo canvas. Route through
    # reset_now so `_last_reset` is populated even before the first
    # scheduled cycle.
    with _canvases._lock:
        c = _canvases._conn()
        count = c.execute(
            "SELECT COUNT(*) FROM canvases WHERE owner_id = ?", (demo_id,)
        ).fetchone()[0]
    if count == 0:
        try:
            reset_now()
        except Exception as exc:
            log.warning("[demo_reset] initial reseed failed: %s", exc)

    if _thread and _thread.is_alive():
        return
    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_scheduler_loop, args=(_stop_event,),
        name="demo-reset", daemon=True,
    )
    _thread.start()
    log.info("[demo_reset] scheduler started")


def stop() -> None:
    """Best-effort shutdown for tests."""
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2.0)
    _stop_event = None
    _thread = None


__all__ = [
    "reset_now", "last_reset", "start", "stop",
    "_seconds_until_next_midnight",
]
