"""Exact sequential top-k optimization at a documented 0.001-point precision."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from time import monotonic

from ortools.sat.python import cp_model

from backend.schemas import OptimizeRequest, PoolImport


def score_units(value: float | None) -> int:
    if value is None:
        raise ValueError("Player projection has not been calculated")
    return int((Decimal(str(value)) * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def optimize(pool: PoolImport, request: OptimizeRequest, timeout: float = 15.0) -> dict:
    known = {p.id for p in pool.players}
    if (set(request.locked) | set(request.excluded)) - known:
        raise ValueError("Selection contains a player outside this pool")
    model = cp_model.CpModel()
    selected = [model.new_bool_var(p.id) for p in pool.players]
    model.add(sum(selected) == pool.rules.roster_size)
    model.add(sum(x * p.price for x, p in zip(selected, pool.players)) <= pool.rules.budget)
    teams = defaultdict(list)
    for x, p in zip(selected, pool.players):
        teams[p.team].append(x)
        if p.id in request.locked:
            model.add(x == 1)
        if p.id in request.excluded:
            model.add(x == 0)
    for members in teams.values():
        model.add(sum(members) <= pool.rules.max_per_team)
    model.maximize(sum(x * score_units(p.projected_points) for x, p in zip(selected, pool.players)))
    lineups = []
    deadline = monotonic() + timeout
    termination = "complete"
    for rank in range(1, 6):
        remaining = deadline - monotonic()
        if remaining <= 0:
            termination = "time_limit"
            break
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.solve(model)
        if status == cp_model.INFEASIBLE:
            termination = "exhausted"
            break
        if status != cp_model.OPTIMAL:
            # Never label a merely feasible roster as the next-best roster.
            termination = "time_limit"
            break
        indices = [i for i, x in enumerate(selected) if solver.value(x)]
        players = [pool.players[i] for i in indices]
        cost = sum(p.price for p in players)
        lineups.append(
            {
                "rank": rank,
                "players": [p.model_dump(mode="json") for p in players],
                "cost": cost,
                "remaining_budget": pool.rules.budget - cost,
                "projected_points": sum(score_units(p.projected_points) for p in players) / 1000,
            }
        )
        model.add(sum(selected[i] for i in indices) <= 5 - request.min_unique)
    return {
        "lineups": lineups,
        "termination": termination,
        "ranking_mode": "top_five" if request.min_unique == 1 else "sequential_diversity",
        "score_precision": 0.001,
        "message": {
            "complete": "Five optimal lineups found under the supplied projections and constraints.",
            "exhausted": "All feasible lineups under these constraints have been returned.",
            "time_limit": "Time limit reached. Only lineups with proven optimality are shown.",
        }[termination],
    }
