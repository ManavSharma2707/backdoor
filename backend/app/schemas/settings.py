"""Business settings (`api-spec.md` section 3). Ranges come from `engine-spec.md`."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.schemas.common import MoneyIn, MoneyStr, reject_float

ServiceLevel = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(ge=Decimal("0.50"), le=Decimal("0.999"), decimal_places=3),
]
ShelfLifeFraction = Annotated[
    Decimal,
    BeforeValidator(reject_float),
    Field(ge=Decimal("0.10"), le=Decimal("1.00"), decimal_places=2),
]


class PriorityWeights(BaseModel):
    """Budget priority weights. They are shares, so they add up to 1."""

    model_config = ConfigDict(extra="forbid")

    risk: float = Field(ge=0, le=1)
    value: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    excess: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sum_to_one(self) -> Self:
        total = self.risk + self.value + self.confidence + self.excess
        if abs(total - 1.0) > 0.001:
            raise ValueError("weights must add up to 1")
        return self


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weekly_budget: MoneyStr | None
    service_level: Decimal = Field(description="Share of demand cycles covered, for example 0.950")
    review_period_days: int
    default_lead_time_days: int
    near_expiry_days: int
    nonmoving_days: int
    slow_cover_days: int
    excess_horizon_days: int
    forecast_horizon_days: int
    backtest_origins: int
    stale_count_days: int
    sellable_shelf_life_fraction: Decimal
    censor_policy: Literal["exclude", "weekday_fill"]
    pack_rounding: Literal["up", "nearest_safe"]
    priority_weights: PriorityWeights
    apply_festival_lead_padding: bool
    agents_enabled: bool


class SettingsPatch(BaseModel):
    """Only the fields that are sent change. `weekly_budget: null` clears the limit."""

    model_config = ConfigDict(extra="forbid")

    weekly_budget: MoneyIn | None = None
    service_level: ServiceLevel | None = None
    review_period_days: int | None = Field(default=None, ge=1, le=28)
    default_lead_time_days: int | None = Field(default=None, ge=0, le=60)
    near_expiry_days: int | None = Field(default=None, ge=7, le=365)
    nonmoving_days: int | None = Field(default=None, ge=14, le=365)
    slow_cover_days: int | None = Field(default=None, ge=14, le=730)
    excess_horizon_days: int | None = Field(default=None, ge=7, le=180)
    forecast_horizon_days: int | None = Field(default=None, ge=14, le=56)
    backtest_origins: int | None = Field(default=None, ge=4, le=26)
    stale_count_days: int | None = Field(default=None, ge=7, le=180)
    sellable_shelf_life_fraction: ShelfLifeFraction | None = None
    censor_policy: Literal["exclude", "weekday_fill"] | None = None
    pack_rounding: Literal["up", "nearest_safe"] | None = None
    priority_weights: PriorityWeights | None = None
    apply_festival_lead_padding: bool | None = None
    agents_enabled: bool | None = None

    @model_validator(mode="after")
    def _only_the_budget_may_be_null(self) -> Self:
        for name in self.model_fields_set:
            if name != "weekly_budget" and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self
