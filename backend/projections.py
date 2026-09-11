"""Transparent baseline; requires comparable historical per-series fantasy scores."""

from datetime import datetime
from math import exp, log


def recent_form_projection(
    matches: list[tuple[datetime, float]],
    as_of: datetime,
    expected_matches: float,
    half_life_days: float = 30,
    padding_points: float = 0,
) -> tuple[float, str]:
    if not matches:
        raise ValueError("At least one historical score is required")
    ages = [(as_of - played_at).total_seconds() / 86400 for played_at, _ in matches]
    if any(age < 0 for age in ages):
        raise ValueError("Historical scores cannot be later than the pool observation time")
    # Shift all ages by the newest match to avoid exponential underflow on old data.
    newest = min(ages)
    weights = [exp(-log(2) * (age - newest) / half_life_days) for age in ages]
    mean = sum(weight * score for weight, (_, score) in zip(weights, matches)) / sum(weights)
    projected = round(mean * expected_matches + padding_points, 3)
    rationale = (
        f"Recency-weighted mean {mean:.2f} pts/series across {len(matches)} series "
        f"× {expected_matches:g} expected series + {padding_points:g} supplied padding points. "
        f"Half-life: {half_life_days:g} days. Opponent strength, roles, and boosters are not modeled."
    )
    return projected, rationale
