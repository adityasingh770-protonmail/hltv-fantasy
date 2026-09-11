import itertools
import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.optimizer import optimize, score_units
from backend.schemas import OptimizeRequest, PoolImport


@pytest.fixture
def pool():
    return PoolImport.model_validate(json.loads(Path("data/sample-pool.json").read_text()))


def brute_force(pool, locked=(), excluded=()):
    legal = []
    for roster in itertools.combinations(pool.players, 5):
        ids = {p.id for p in roster}
        if not set(locked) <= ids or set(excluded) & ids:
            continue
        if sum(p.price for p in roster) > pool.rules.budget:
            continue
        if max(Counter(p.team for p in roster).values()) > pool.rules.max_per_team:
            continue
        legal.append((sum(score_units(p.projected_points) for p in roster), ids))
    return sorted(legal, key=lambda x: x[0], reverse=True)


@pytest.mark.parametrize("locked,excluded", [((), ()), (("nova",), ("axis",)), (("foam", "glow"), ())])
def test_top_five_matches_exhaustive_search(pool, locked, excluded):
    result = optimize(pool, OptimizeRequest(pool_id="test", locked=list(locked), excluded=list(excluded)))
    expected = brute_force(pool, locked, excluded)
    assert [round(r["projected_points"] * 1000) for r in result["lineups"]] == [s for s, _ in expected[:5]]
    rosters = [frozenset(p["id"] for p in row["players"]) for row in result["lineups"]]
    assert len(set(rosters)) == 5
    for row in result["lineups"]:
        assert row["cost"] <= pool.rules.budget
        assert len(row["players"]) == 5
        assert max(Counter(p["team"] for p in row["players"]).values()) <= pool.rules.max_per_team


def test_diversity_is_optimal_at_each_step(pool):
    result = optimize(pool, OptimizeRequest(pool_id="test", min_unique=3))
    candidates = brute_force(pool)
    for row in result["lineups"]:
        ids = {p["id"] for p in row["players"]}
        assert round(row["projected_points"] * 1000) == candidates[0][0]
        candidates = [(score, roster) for score, roster in candidates if len(roster & ids) <= 2]


def test_fewer_than_five_and_infeasible(pool):
    fixed = brute_force(pool)[0][1]
    result = optimize(pool, OptimizeRequest(pool_id="test", locked=list(fixed)))
    assert len(result["lineups"]) == 1
    assert result["termination"] == "exhausted"
    pool.rules.budget = 1
    assert optimize(pool, OptimizeRequest(pool_id="test"))["lineups"] == []


def test_timeout_does_not_claim_top_five(pool):
    result = optimize(pool, OptimizeRequest(pool_id="test"), timeout=0)
    assert result["termination"] == "time_limit"
    assert result["lineups"] == []


def test_unknown_player_and_conflicting_constraints(pool):
    with pytest.raises(ValueError, match="outside"):
        optimize(pool, OptimizeRequest(pool_id="test", locked=["missing"]))
    with pytest.raises(ValidationError):
        OptimizeRequest(pool_id="test", locked=["nova"], excluded=["nova"])


@pytest.mark.parametrize("change", ["duplicates", "nan", "negative_price", "timezone"])
def test_pool_validation(pool, change):
    data = pool.model_dump(mode="json")
    if change == "duplicates":
        data["players"][1]["id"] = data["players"][0]["id"]
    elif change == "nan":
        data["players"][0]["projected_points"] = float("nan")
    elif change == "negative_price":
        data["players"][0]["price"] = -1
    else:
        data["observed_at"] = "2026-09-10T00:00:00"
    with pytest.raises(ValidationError):
        PoolImport.model_validate(data)
