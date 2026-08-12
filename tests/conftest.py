"""Shared pytest fixtures.

v0.8.0: activate the DRAWLANG_TEST_BYPASS_AUTH switch so the auth
middleware auto-injects a synthetic admin for every request. This keeps
the pre-auth test suite (276+ tests, some of which build TestClient at
module import time) green without a rewrite. Auth-specific tests set
their own headers/cookies and can override this bypass.

The ownership.owner_id column is added by each domain module's
``init()`` (via a direct call to ``ownership._apply_one``), so tests
that use temp DBs no longer need a separate migration step.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("DRAWLANG_TEST_BYPASS_AUTH", "1")

# Ensure `from app import ...` resolves regardless of which test file
# runs first. Historically the earliest test file did this side-effect;
# tests that assumed it (e.g. test_v077_selection_cmds.py) broke when
# selected alone.
_ROOT = Path(__file__).resolve().parent.parent
_EDITOR_DIR = str(_ROOT / "editor")
if _EDITOR_DIR not in sys.path:
    sys.path.insert(0, _EDITOR_DIR)
