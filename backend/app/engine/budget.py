"""Budget allocation (`engine-spec.md` section 12).

Lines are funded in order of a transparent priority score, in whole packs. Spend never goes past
the budget, and the result says plainly how much of the need is left unfunded.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import numpy as np

from app.engine.constants import CONFIDENCE_SCORE, DEFAULT_WEIGHTS
from app.engine.types import FloatArray

PAISA = Decimal("0.01")


@dataclass(frozen=True)
class BudgetLine:
    """What the allocator needs to know about a line that wants stock."""

    key: str
    packs: int
    pack_size: Decimal
    moq_units: Decimal
    unit_cost: Decimal | None
    stockout_probability: float
    expected_margin: float
    confidence: str
    excess_ratio: float
    critical: bool = False

    @property
    def pack_cost(self) -> Decimal | None:
        return None if self.unit_cost is None else (self.pack_size * self.unit_cost)

    @property
    def full_spend(self) -> Decimal | None:
        cost = self.pack_cost
        return None if cost is None else (cost * self.packs).quantize(PAISA)

    @property
    def min_packs(self) -> int:
        """Smallest number of whole packs that meets the supplier minimum (at least one)."""
        if self.pack_size <= 0:
            return 1
        return max(1, math.ceil(self.moq_units / self.pack_size))


@dataclass
class Allocation:
    key: str
    packs: int
    qty: Decimal
    spend: Decimal
    unfunded_packs: int
    budget_limited: bool
    score: float | None
    components: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False  # no cost known, so it cannot be funded or ordered


@dataclass
class BudgetResult:
    allocations: dict[str, Allocation]
    budget: Decimal | None
    needed: Decimal
    funded: Decimal
    shortfall: Decimal
    unfunded_value: Decimal
    unfunded_lines: int
    blocked_lines: int
    weights: dict[str, float]

    @property
    def constrained(self) -> bool:
        return self.budget is not None and self.needed > self.budget


def percentile_ranks(values: Sequence[float]) -> FloatArray:
    """Rank of each value among all, from 0 (lowest) to 1 (highest), ties share their average."""
    n = len(values)
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.ones(1)
    arr = np.asarray(values, dtype=np.float64)
    order = np.argsort(arr, kind="stable")
    ranks = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and arr[order[j + 1]] == arr[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0
        i = j + 1
    return ranks / (n - 1)


def priority_scores(
    lines: Sequence[BudgetLine], weights: Mapping[str, float]
) -> dict[str, tuple[float, dict[str, float]]]:
    """`w_risk * risk + w_value * value + w_conf * confidence - w_excess * excess`, each part in
    0 to 1. The value part is the percentile rank of the expected margin among the lines."""
    w = {**DEFAULT_WEIGHTS, **weights}
    value = percentile_ranks([ln.expected_margin for ln in lines])
    out: dict[str, tuple[float, dict[str, float]]] = {}
    for ln, v in zip(lines, value, strict=True):
        parts = {
            "risk": min(max(ln.stockout_probability, 0.0), 1.0),
            "value": float(v),
            "confidence": CONFIDENCE_SCORE.get(ln.confidence, 0.4),
            "excess": min(max(ln.excess_ratio, 0.0), 1.0),
        }
        score = (
            w["risk"] * parts["risk"]
            + w["value"] * parts["value"]
            + w["confidence"] * parts["confidence"]
            - w["excess"] * parts["excess"]
        )
        out[ln.key] = (round(score, 4), {k: round(x, 4) for k, x in parts.items()})
    return out


def allocate(
    lines: Sequence[BudgetLine], budget: Decimal | None, weights: Mapping[str, float]
) -> BudgetResult:
    """Fund lines in score order. A line that does not fit gets the largest whole number of packs
    that does and still meets its minimum order, or nothing, and the next line is tried."""
    w = {**DEFAULT_WEIGHTS, **weights}
    wanting = [ln for ln in lines if ln.packs > 0]
    costed = [ln for ln in wanting if ln.unit_cost is not None]
    blocked = [ln for ln in wanting if ln.unit_cost is None]
    scores = priority_scores(costed, w)
    needed = sum((ln.full_spend or Decimal(0) for ln in costed), Decimal(0))
    unconstrained = budget is None or needed <= budget
    remaining = budget if budget is not None else Decimal(0)
    allocations: dict[str, Allocation] = {}

    order = sorted(
        costed,
        key=lambda ln: (
            -scores[ln.key][0],
            -ln.stockout_probability,
            ln.full_spend or Decimal(0),
            ln.key,
        ),
    )
    for ln in order:
        cost = ln.pack_cost or Decimal(0)
        score, parts = scores[ln.key]
        packs = ln.packs
        if not unconstrained:
            full = ln.full_spend or Decimal(0)
            if full <= remaining:
                packs = ln.packs
            elif cost > 0:
                fit = int((remaining / cost).to_integral_value(rounding=ROUND_FLOOR))
                packs = fit if fit >= ln.min_packs else 0
            else:
                packs = ln.packs
        spend = (cost * packs).quantize(PAISA)
        if not unconstrained:
            remaining -= spend
        allocations[ln.key] = Allocation(
            key=ln.key,
            packs=packs,
            qty=ln.pack_size * packs,
            spend=spend,
            unfunded_packs=ln.packs - packs,
            budget_limited=packs < ln.packs,
            score=score,
            components={**parts, "weights": w},
        )
    for ln in blocked:
        allocations[ln.key] = Allocation(
            key=ln.key,
            packs=0,
            qty=Decimal(0),
            spend=Decimal(0),
            unfunded_packs=ln.packs,
            budget_limited=False,
            score=None,
            blocked=True,
        )
    funded = sum((a.spend for a in allocations.values()), Decimal(0))
    by_key = {ln.key: ln for ln in costed}
    unfunded_value = sum(
        (
            (by_key[a.key].pack_cost or Decimal(0)) * a.unfunded_packs
            for a in allocations.values()
            if not a.blocked
        ),
        Decimal(0),
    ).quantize(PAISA)
    shortfall = max(needed - budget, Decimal(0)) if budget is not None else Decimal(0)
    return BudgetResult(
        allocations=allocations,
        budget=budget,
        needed=needed.quantize(PAISA),
        funded=funded.quantize(PAISA),
        shortfall=shortfall.quantize(PAISA),
        unfunded_value=unfunded_value,
        unfunded_lines=sum(1 for a in allocations.values() if a.budget_limited),
        blocked_lines=len(blocked),
        weights=w,
    )
