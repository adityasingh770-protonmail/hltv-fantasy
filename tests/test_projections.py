import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.projections import recent_form_projection
from backend.schemas import PoolImport


def test_recency_weighting_and_expected_series():
    # The older score is exactly one half-life earlier, so it has half the weight.
    score, explanation = recent_form_projection(
        [(datetime(2026, 8, 11, tzinfo=UTC), 10), (datetime(2026, 9, 10, tzinfo=UTC), 40)],
        datetime(2026, 9, 10, tzinfo=UTC),
        expected_matches=4,
        padding_points=6,
    )
    assert score == 126
    assert "30.00 pts/series" in explanation


def test_future_match_rejected():
    with pytest.raises(ValueError, match="later"):
        recent_form_projection(
            [(datetime(2026, 9, 11, tzinfo=UTC), 40)], datetime(2026, 9, 10, tzinfo=UTC), 4
        )


def test_history_import_normalizes_projection():
    data = json.loads(Path("data/sample-pool.json").read_text())
    player = data["players"][0]
    player.pop("projected_points")
    player.pop("rationale")
    player["recent_form"] = {
        "matches": [{"played_at": "2026-09-09T00:00:00Z", "fantasy_points": -5}],
        "expected_matches": 3,
    }
    normalized = PoolImport.model_validate(data)
    assert normalized.players[0].projected_points == -15
    assert "recent-form-v1" in normalized.projection_method
    assert PoolImport.model_validate(normalized.model_dump()).players[0].projected_points == -15
    player["recent_form"]["expected_matches"] = 0
    with pytest.raises(ValidationError):
        PoolImport.model_validate(data)
