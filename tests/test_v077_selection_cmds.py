"""v0.7.7 — selection-transform NLP parser + /api/nlp/selection endpoint.

Grammar remains frozen at v0.6. These tests only cover the new natural-
language selection-command layer (mouse/keyboard/mic voice) which is
translated to *existing* PATCH operations by the frontend.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import selection_cmds
from app.main import app


# ---------------------------------------------------------------------------
# Unit tests — the pure parser
# ---------------------------------------------------------------------------


def test_shift_basic_english() -> None:
    assert selection_cmds.parse("move right 50") == {"op": "shift", "dx": 50, "dy": 0}
    assert selection_cmds.parse("move left 25") == {"op": "shift", "dx": -25, "dy": 0}
    assert selection_cmds.parse("go up 5") == {"op": "shift", "dx": 0, "dy": 5}
    assert selection_cmds.parse("nudge down 12") == {"op": "shift", "dx": 0, "dy": -12}


def test_shift_verbose_english() -> None:
    r = selection_cmds.parse("please move the selection to the right by 50 pixels")
    assert r == {"op": "shift", "dx": 50, "dy": 0}
    r = selection_cmds.parse("shift left by 20 mm")
    assert r == {"op": "shift", "dx": -20, "dy": 0}


def test_shift_bareword_direction() -> None:
    assert selection_cmds.parse("right 20") == {"op": "shift", "dx": 20, "dy": 0}
    assert selection_cmds.parse("up 5") == {"op": "shift", "dx": 0, "dy": 5}


def test_shift_defaults_to_10() -> None:
    # "move right" with no number defaults to 10 units — matches keyboard nudge step.
    assert selection_cmds.parse("move right") == {"op": "shift", "dx": 10, "dy": 0}


def test_shift_czech_directions() -> None:
    assert selection_cmds.parse("posun doprava 30") == {"op": "shift", "dx": 30, "dy": 0}
    assert selection_cmds.parse("jdi nahoru 15") == {"op": "shift", "dx": 0, "dy": 15}


def test_scale_percentage() -> None:
    r = selection_cmds.parse("bigger 20%")
    assert r["op"] == "scale" and abs(r["factor"] - 1.2) < 1e-9
    r = selection_cmds.parse("smaller 10%")
    assert r["op"] == "scale" and abs(r["factor"] - 0.9) < 1e-9


def test_scale_no_number_defaults_to_10pct() -> None:
    r = selection_cmds.parse("bigger")
    assert r["op"] == "scale" and abs(r["factor"] - 1.1) < 1e-9
    r = selection_cmds.parse("smaller")
    assert r["op"] == "scale" and abs(r["factor"] - 0.9) < 1e-9


def test_scale_absolute_factor() -> None:
    r = selection_cmds.parse("scale 0.5")
    assert r["op"] == "scale" and r["factor"] == 0.5
    r = selection_cmds.parse("scale to 150%")
    assert r["op"] == "scale" and abs(r["factor"] - 1.5) < 1e-9


def test_scale_words() -> None:
    assert selection_cmds.parse("double the size") == {"op": "scale", "factor": 2.0}
    assert selection_cmds.parse("half the size") == {"op": "scale", "factor": 0.5}
    assert selection_cmds.parse("twice as big") == {"op": "scale", "factor": 2.0}


def test_unparseable_command_raises() -> None:
    with pytest.raises(selection_cmds.SelectionCommandError):
        selection_cmds.parse("draw a circle")
    with pytest.raises(selection_cmds.SelectionCommandError):
        selection_cmds.parse("")


def test_negative_or_zero_scale_rejected() -> None:
    with pytest.raises(selection_cmds.SelectionCommandError):
        selection_cmds.parse("scale 0")
    with pytest.raises(selection_cmds.SelectionCommandError):
        selection_cmds.parse("bigger 0%")


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_endpoint_returns_action_shift() -> None:
    with TestClient(app) as c:
        r = c.post("/api/nlp/selection", json={"text": "move right 25"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["action"] == {"op": "shift", "dx": 25, "dy": 0}


def test_endpoint_returns_action_scale() -> None:
    with TestClient(app) as c:
        r = c.post("/api/nlp/selection", json={"text": "bigger 20%"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["action"]["op"] == "scale"
        assert abs(j["action"]["factor"] - 1.2) < 1e-9


def test_endpoint_400_on_unparseable() -> None:
    with TestClient(app) as c:
        r = c.post("/api/nlp/selection", json={"text": "draw a circle here"})
        assert r.status_code == 400
        assert "can't parse" in r.json()["detail"] or "try" in r.json()["detail"]


def test_endpoint_does_not_mutate_canvas() -> None:
    """Endpoint is a pure parser; it must not touch state or the DB."""
    with TestClient(app) as c:
        r = c.post("/api/nlp/selection", json={"text": "move right 100"})
        assert r.status_code == 200
        # No canvas_id in the request, no side effects.
        assert "inserted" not in r.json()
        assert "program" not in r.json()


def test_health_reports_v077() -> None:
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["semantic_layer"] == "0.7.7"
