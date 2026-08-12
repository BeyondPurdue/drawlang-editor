"""
Demo user nightly reset (v0.8.0).

Wipes every canvas, frame, and library item owned by the demo user, then
reseeds a minimal set. Runs in a background daemon thread; the schedule
target is the next midnight in Europe/Madrid.

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
# Seed programs
# ---------------------------------------------------------------------------

_DEMO_CANVAS_SEEDS: list[dict] = [
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


_DEMO_LIBRARY_SEEDS: list[dict] = [
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


def _reseed(demo_id: int) -> None:
    """Insert the seed content owned by demo. Never raises."""
    for spec in _DEMO_CANVAS_SEEDS:
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
    for spec in _DEMO_LIBRARY_SEEDS:
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


def reset_now() -> dict:
    """Perform one reset cycle: wipe + reseed. Returns counts wiped."""
    try:
        demo_id = _auth.demo_user_id()
    except Exception:
        return {"ok": False, "reason": "demo user not initialised"}
    n_c, n_f, n_l = _delete_all_for_owner(demo_id)
    _reseed(demo_id)
    log.info(
        "[demo_reset] wiped %s canvas / %s frame / %s library, reseeded",
        n_c, n_f, n_l,
    )
    return {"ok": True, "canvases": n_c, "frames": n_f, "library": n_l}


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
    # fresh deploy still greets the user with a demo canvas.
    with _canvases._lock:
        c = _canvases._conn()
        count = c.execute(
            "SELECT COUNT(*) FROM canvases WHERE owner_id = ?", (demo_id,)
        ).fetchone()[0]
    if count == 0:
        try:
            _reseed(demo_id)
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


__all__ = ["reset_now", "start", "stop", "_seconds_until_next_midnight"]
