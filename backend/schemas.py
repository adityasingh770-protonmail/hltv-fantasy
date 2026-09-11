from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from backend.projections import recent_form_projection


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Rules(StrictModel):
    budget: int = Field(gt=0, le=10_000_000)
    roster_size: Literal[5] = 5
    max_per_team: int = Field(ge=1, le=5)


class MatchScore(StrictModel):
    played_at: datetime
    fantasy_points: float = Field(ge=-1000, le=1000)

    @model_validator(mode="after")
    def timezone_required(self):
        if self.played_at.tzinfo is None:
            raise ValueError("Historical score timestamps must include a timezone")
        return self


class RecentForm(StrictModel):
    matches: list[MatchScore] = Field(min_length=1, max_length=100)
    expected_matches: float = Field(gt=0, le=30)
    half_life_days: float = Field(default=30, ge=1, le=365)
    padding_points: float = Field(default=0, ge=-1000, le=1000)


class Player(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    team: str = Field(min_length=1, max_length=80)
    price: int = Field(gt=0, le=10_000_000)
    projected_points: float | None = Field(default=None, ge=-100_000, le=100_000)
    rationale: str = Field(default="", max_length=1000)
    recent_form: RecentForm | None = None

    @model_validator(mode="after")
    def projection_required(self):
        if self.recent_form is None and (self.projected_points is None or not self.rationale):
            raise ValueError("Supply recent_form, or projected_points and a rationale")
        return self


class PoolImport(StrictModel):
    event_id: str = Field(min_length=1, max_length=80)
    event_name: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl
    observed_at: datetime
    lock_at: datetime | None = None
    is_demo: bool = False
    rules_verified: bool = False
    projection_method: str = Field(min_length=1, max_length=2000)
    rules: Rules
    players: list[Player] = Field(min_length=5, max_length=200)

    @model_validator(mode="after")
    def validate_pool(self):
        if self.observed_at.tzinfo is None or (self.lock_at and self.lock_at.tzinfo is None):
            raise ValueError("Timestamps must include a timezone")
        ids = [p.id for p in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("Player IDs must be unique")
        uses_form = False
        for player in self.players:
            form = player.recent_form
            if form is not None:
                uses_form = True
                player.projected_points, player.rationale = recent_form_projection(
                    [(match.played_at, match.fantasy_points) for match in form.matches],
                    self.observed_at,
                    form.expected_matches,
                    form.half_life_days,
                    form.padding_points,
                )
        if uses_form:
            self.projection_method = (
                "recent-form-v1: recency-weighted historical points per series × supplied expected series "
                "+ supplied padding. Players without recent_form retain their supplied projections. "
                "Expected series and historical scores are importer inputs, not verified predictions."
            )
        return self


class OptimizeRequest(StrictModel):
    pool_id: str
    locked: list[str] = Field(default_factory=list, max_length=5)
    excluded: list[str] = Field(default_factory=list, max_length=200)
    min_unique: int = Field(default=1, ge=1, le=5)

    @model_validator(mode="after")
    def validate_selection(self):
        if len(set(self.locked)) != len(self.locked) or len(set(self.excluded)) != len(self.excluded):
            raise ValueError("Selections must not contain duplicate player IDs")
        if set(self.locked) & set(self.excluded):
            raise ValueError("A player cannot be both locked and excluded")
        return self
