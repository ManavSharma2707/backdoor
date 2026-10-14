"""Grade the forecasts against the hidden true demand of the synthetic tenants.

`python -m seed.accuracy [--with-lgbm]` writes `backend/reports/synthetic_accuracy.md`.

The seed keeps what customers really wanted each day (`synthetic_true_demand`), including the
sales that were lost when a shelf was empty. No product code path reads that table: only this
evaluation script does. The results describe the method on simulated data. They are never
customer results (`D-040`).

Honest protocol: methods are chosen on the 12 weeks before the grading window, then graded on the
last 12 weeks, so the choice never sees the weeks it is graded on. Event effects come from the
same earlier weeks.
"""

import argparse
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_session_factory
from app.engine.backtest import run_backtest
from app.engine.demand_class import classify_demand
from app.engine.event_effects import effective_records, learn_event_effects
from app.engine.forecast import category_means, effect_matrices, training_data
from app.engine.methods import STATISTICAL_METHODS, MethodContext
from app.engine.selection import select_methods
from app.engine.types import Series
from app.services.plan_data import PlanLoader

REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "synthetic_accuracy.md"
AS_OF = date(2026, 10, 12)
N_WINDOW = 12
METHODS = ("seasonal_naive", "moving_average", "weekday_profile", "ses_weekday", "croston_sba")
BASELINES = ("moving_average_28", "seasonal_naive")


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


@dataclass
class Tally:
    """Absolute error, true demand, signed error and count of one group."""

    abs_err: float = 0.0
    total: float = 0.0
    signed: float = 0.0
    n: int = 0

    def add(self, forecast: np.ndarray, actual: np.ndarray) -> None:
        self.abs_err += float(np.abs(forecast - actual).sum())
        self.total += float(actual.sum())
        self.signed += float((forecast - actual).sum())
        self.n += int(actual.size)

    @property
    def wape(self) -> float | None:
        return self.abs_err / self.total if self.total > 0 else None

    @property
    def bias(self) -> float | None:
        return self.signed / self.total if self.total > 0 else None

    @property
    def mae(self) -> float:
        return self.abs_err / self.n if self.n else 0.0


@dataclass
class TenantEval:
    slug: str
    name: str
    business_type: str
    n_products: int
    by_method_true: dict[str, Tally] = field(default_factory=dict)
    by_method_observed: dict[str, Tally] = field(default_factory=dict)
    by_class: dict[str, dict[str, Tally]] = field(default_factory=lambda: defaultdict(dict))
    by_category: dict[str, dict[str, Tally]] = field(default_factory=lambda: defaultdict(dict))
    selected_methods: dict[str, int] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)
    lgbm: dict[str, Any] | None = None
    classes: dict[str, int] = field(default_factory=dict)
    effect_days: dict[str, Tally] = field(default_factory=dict)


def true_matrix(
    session: Session, tenant_id: uuid.UUID, product_ids: list[uuid.UUID], start: date, n_days: int
) -> tuple[np.ndarray, dict[tuple[uuid.UUID, date], float]]:
    index = {pid: i for i, pid in enumerate(product_ids)}
    true = np.zeros((len(product_ids), n_days))
    multiplier: dict[tuple[uuid.UUID, date], float] = {}
    rows = session.execute(
        text(
            "SELECT product_id, stat_date, true_demand, event_multiplier FROM synthetic_true_demand "
            "WHERE tenant_id = :t AND stat_date >= :s"
        ),
        {"t": tenant_id, "s": start},
    )
    for pid, day, demand, mult in rows:
        d = (day - start).days
        if pid in index and 0 <= d < n_days:
            true[index[pid], d] = float(demand)
            multiplier[(pid, day)] = float(mult or 1.0)
    return true, multiplier


def evaluate(session: Session, tenant_id: uuid.UUID, with_lgbm: bool) -> TenantEval:
    loader = PlanLoader(session, tenant_id, AS_OF)
    tenant = loader.tenant()
    suppliers = loader.suppliers()
    history = loader.history()
    products = {p.id: p for p in loader.products(history, suppliers)}
    prods = [products[pid] for pid in history.product_ids]
    events = loader.calendar_events()
    training = training_data(history.units, history.codes, history.promo, history.start)
    n_products, n_days = training.trusted.shape
    true, event_mult = true_matrix(session, tenant_id, history.product_ids, history.start, n_days)
    result = TenantEval(tenant.slug, tenant.name, tenant.business_type, n_products)

    category_keys = sorted({str(p.category_id) for p in prods})
    code_of = {k: i for i, k in enumerate(category_keys)}
    codes = np.array([code_of[str(p.category_id)] for p in prods], dtype=np.int64)
    slugs = [p.category_slug for p in prods]
    names = {str(p.category_id): p.category_name for p in prods}
    is_medical = tenant.business_type == "medical"

    cut = n_days - 7 * N_WINDOW  # the grading window starts here
    y_train = training.trusted[:, :cut]
    classes = [classify_demand(y_train[i]).demand_class for i in range(n_products)]
    result.classes = {c: classes.count(c) for c in sorted(set(classes))}
    eligible = np.array([c not in ("new", "no_history") for c in classes])
    cmean = category_means(y_train, codes, len(category_keys), eligible)
    cat_means = [None if np.isnan(cmean[c]) else float(cmean[c]) for c in codes]

    # Effects and selection come from the weeks before the grading window only.
    learned = learn_event_effects(
        events=events,
        y=y_train,
        start=history.start,
        category_codes=codes,
        category_keys=category_keys,
        is_medical=is_medical,
    )
    applied = list(effective_records(learned).values())
    mult, _ = effect_matrices(
        applied,
        events,
        category_keys=category_keys,
        category_codes=codes,
        promotions=[],
        start=history.start,
        n_days=n_days,
    )
    adjusted = training.trusted / mult[:, :n_days]
    data = run_backtest(
        y_train=adjusted[:, :cut],
        y_eval=training.trusted[:, :cut],
        multipliers=mult[:, :cut],
        start=history.start,
        classes=classes,
        category_means=cat_means,
        n_origins=12,
    )
    selection = select_methods(
        data,
        classes=classes,
        category_slugs=slugs,
        product_keys=[str(p) for p in history.product_ids],
    )
    chosen: list[str] = []
    for i, klass in enumerate(classes):
        if klass in ("new", "no_history"):
            chosen.append("category_prior" if klass == "no_history" else "moving_average")
        else:
            chosen.append(selection.resolve(f"{slugs[i]}|{klass}", klass, allow_lgbm=False)[0])
    result.selected_methods = {m: chosen.count(m) for m in sorted(set(chosen))}

    result.effect_days = {"with": Tally(), "without": Tally()}
    names_list = [*METHODS, "moving_average_28", "selected", "selected_without_effects"]
    for name in names_list:
        result.by_method_true[name] = Tally()
        result.by_method_observed[name] = Tally()
    for klass in sorted(set(classes)):
        result.by_class[klass] = {
            n: Tally() for n in ("selected", "moving_average_28", "seasonal_naive")
        }
    for key in category_keys:
        result.by_category[names[key]] = {n: Tally() for n in ("selected", "moving_average_28")}

    for k in range(N_WINDOW, 0, -1):
        o = n_days - 7 * k
        dates = [history.start + timedelta(days=o + i) for i in range(7)]
        actual_true = true[:, o : o + 7]
        observed = training.trusted[:, o : o + 7]
        for p in range(n_products):
            klass = classes[p]
            series = Series(history.start, adjusted[p, :o])
            raw_series = Series(history.start, training.trusted[p, :o])
            ctx = MethodContext(demand_class=klass, category_mean=cat_means[p])
            ctx28 = MethodContext(demand_class=klass, moving_average_window=28)
            m7 = mult[p, o : o + 7]
            forecasts: dict[str, np.ndarray] = {}
            for name in METHODS:
                forecasts[name] = np.maximum(
                    STATISTICAL_METHODS[name](series, dates, ctx).yhat * m7, 0.0
                )
            forecasts["moving_average_28"] = np.maximum(
                STATISTICAL_METHODS["moving_average"](series, dates, ctx28).yhat * m7, 0.0
            )
            sel = chosen[p] if chosen[p] in STATISTICAL_METHODS else "moving_average"
            forecasts["selected"] = (
                forecasts[sel]
                if sel in forecasts
                else np.maximum(STATISTICAL_METHODS[sel](series, dates, ctx).yhat * m7, 0.0)
            )
            forecasts["selected_without_effects"] = np.maximum(
                STATISTICAL_METHODS[sel](raw_series, dates, ctx).yhat, 0.0
            )
            moved = m7 != 1.0
            if moved.any():
                result.effect_days["with"].add(forecasts["selected"][moved], actual_true[p][moved])
                result.effect_days["without"].add(
                    forecasts["selected_without_effects"][moved], actual_true[p][moved]
                )
            ok = ~np.isnan(observed[p])
            for name, f in forecasts.items():
                result.by_method_true[name].add(f, actual_true[p])
                if ok.any():
                    result.by_method_observed[name].add(f[ok], observed[p][ok])
            for name in ("selected", "moving_average_28", "seasonal_naive"):
                result.by_class[klass][name].add(forecasts[name], actual_true[p])
            for name in ("selected", "moving_average_28"):
                result.by_category[names[category_keys[codes[p]]]][name].add(
                    forecasts[name], actual_true[p]
                )

    result.effects = grade_effects(
        learned, event_mult, history.start, prods, names, history.product_ids
    )
    if with_lgbm:
        result.lgbm = grade_lgbm(
            training, history, events, codes, true, chosen, classes, cat_means, cut
        )
    return result


def grade_effects(
    learned: list[Any],
    event_mult: dict[tuple[uuid.UUID, date], float],
    start: date,
    prods: list[Any],
    names: dict[str, str],
    product_ids: list[uuid.UUID],
) -> dict[str, Any]:
    """Compare each learned effect with the true multiplier of the same days.

    Only festival effects have a recorded truth (`event_multiplier`). A season, a month start or
    a price change also moves sales but is not recorded, so a learned effect with a true
    multiplier of 1 is not necessarily wrong. It is counted separately.
    """
    by_cat: dict[str, list[uuid.UUID]] = defaultdict(list)
    for p in prods:
        by_cat[str(p.category_id)].append(p.id)
    tp = fp = fn = tn = 0
    errors: list[float] = []
    planted_missed: list[tuple[str, str, float]] = []
    false_positives: list[tuple[str, str, str, float, float]] = []
    kinds = {"monsoon", "summer", "winter"}
    for e in learned:
        if e.event_key in kinds:
            continue
        values = []
        for occ in e.evidence.get("occurrences", []):
            d = date.fromisoformat(occ["start"])
            end = date.fromisoformat(occ["end"])
            while d <= end:
                values.extend(
                    event_mult.get((pid, d), 1.0) for pid in by_cat.get(e.category_key, [])
                )
                d += timedelta(days=1)
        truth = float(np.mean(values)) if values else 1.0
        real = abs(truth - 1.0) >= 0.15
        if e.is_applied and real:
            tp += 1
            errors.append(abs(e.evidence["raw_multiplier"] - truth) / truth)
        elif e.is_applied:
            fp += 1
            false_positives.append(
                (
                    e.event_key,
                    e.window,
                    names.get(e.category_key, ""),
                    e.multiplier,
                    round(truth, 2),
                )
            )
        elif real:
            fn += 1
            if abs(truth - 1.0) >= 0.5:
                planted_missed.append((e.event_key, names.get(e.category_key, ""), round(truth, 2)))
        else:
            tn += 1
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "median_relative_error": float(np.median(errors)) if errors else None,
        "strong_missed": sorted(planted_missed, key=lambda r: -abs(r[2] - 1))[:8],
        "false_positives": false_positives[:8],
        "applied": sum(1 for e in learned if e.is_applied),
        "computed": len(learned),
    }


def grade_lgbm(
    training: Any,
    history: Any,
    events: list[Any],
    codes: np.ndarray,
    true: np.ndarray,
    chosen: list[str],
    classes: list[str],
    cat_means: list[float | None],
    cut: int,
) -> dict[str, Any]:
    """The global model on the newest four weeks of the window, against the statistical winner."""
    from app.engine.features import FeatureBuilder, FeatureInputs, price_ratio_matrix
    from app.engine.methods.lgbm import run_global_model

    n_products = training.trusted.shape[0]
    horizon = 28
    promo = np.zeros((n_products, cut + horizon), dtype=bool)
    promo[:, :cut] = history.promo[:, :cut]
    inputs = FeatureInputs(
        y=training.trusted[:, :cut],
        start=history.start,
        category_codes=codes,
        promo=promo,
        price_ratio=price_ratio_matrix(history.units[:, :cut], history.revenue[:, :cut]),
        events=events,
        horizon=horizon,
    )
    model = run_global_model(
        FeatureBuilder(inputs), horizon=horizon, n_backtest_origins=4, n_rank_origins=12
    )
    lg, base, ma = Tally(), Tally(), Tally()
    # The model was trained up to `cut`, so its backtest origins are the 4 weeks before it.
    for j in range(1, 5):
        o = cut - 7 * j
        dates = [history.start + timedelta(days=o + i) for i in range(7)]
        for p in range(n_products):
            forecast = model.backtest.get((p, 12 - j))
            if forecast is None or classes[p] in ("new", "no_history"):
                continue
            series = Series(history.start, training.trusted[p, :o])
            ctx = MethodContext(demand_class=classes[p], category_mean=cat_means[p])
            sel = chosen[p] if chosen[p] in STATISTICAL_METHODS else "moving_average"
            base_f = STATISTICAL_METHODS[sel](series, dates, ctx).yhat
            ma_f = STATISTICAL_METHODS["moving_average"](series, dates, ctx).yhat
            actual = true[p, o : o + 7]
            lg.add(forecast, actual)
            base.add(base_f, actual)
            ma.add(ma_f, actual)
    return {
        "model": lg,
        "statistical": base,
        "moving_average": ma,
        "objective": model.objective,
        "rows": model.n_rows,
        "trees": model.n_trees,
    }


# --------------------------------------------------------------------------- report


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def signed_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


def render(evals: list[TenantEval], with_lgbm: bool) -> str:
    lines = [
        "# Synthetic accuracy report",
        "",
        "Generated by `python -m seed.accuracy`. **All numbers come from simulated data with a hidden "
        "ground truth. They describe how the method behaves on that data. They are not results from real "
        "businesses and must never be quoted as customer savings (D-040).**",
        "",
        "## Protocol",
        "",
        f"- Plan date {AS_OF.isoformat()}. The grading window is the last {N_WINDOW} weeks of history, "
        "forecast one Monday at a time (7 days ahead) with nothing after the origin visible.",
        f"- The method for each segment is chosen on the {N_WINDOW} weeks before the window and event "
        "effects are learned from the same earlier weeks, so no choice sees the weeks it is graded on.",
        "- Truth is `synthetic_true_demand`: what customers wanted, including sales lost to empty shelves. "
        "The same forecasts are also graded against observed sales on trusted days, the way the app measures "
        "itself, to show how censoring changes the picture.",
        "- WAPE is the sum of absolute errors over the sum of demand. Bias is the signed version. "
        "Baselines: the 28 day moving average and same weekday last week.",
        "",
    ]
    for ev in evals:
        t = ev.by_method_true
        sel, base, naive = t["selected"], t["moving_average_28"], t["seasonal_naive"]
        gain = (
            None
            if not base.wape
            else (base.wape - sel.wape) / base.wape
            if sel.wape is not None
            else None
        )
        lines += [
            f"## {ev.name} ({ev.business_type}, {ev.n_products} products)",
            "",
            f"Demand classes: {', '.join(f'{k} {v}' for k, v in ev.classes.items())}. "
            f"Methods chosen: {', '.join(f'{k} {v}' for k, v in ev.selected_methods.items())}.",
            "",
            "| Method | WAPE vs true demand | Bias vs true demand | WAPE vs observed sales |",
            "|---|---|---|---|",
        ]
        for name in (*METHODS, "moving_average_28", "selected", "selected_without_effects"):
            row, obs = t[name], ev.by_method_observed[name]
            label = {
                "selected": "**Selected per segment (with effects)**",
                "selected_without_effects": "Selected, no event effects",
                "moving_average_28": "Baseline: moving average 28",
            }.get(name, name)
            lines.append(
                f"| {label} | {pct(row.wape)} | {signed_pct(row.bias)} | {pct(obs.wape)} |"
            )
        verdict = (
            "beats"
            if gain is not None and gain > 0.005
            else "ties"
            if gain is not None and abs(gain) <= 0.005
            else "does not beat"
        )
        lines += [
            "",
            f"The selected methods {verdict} the 28 day moving average on true demand "
            f"({'n/a' if gain is None else f'{gain * 100:+.1f}%'} change in WAPE) and "
            f"{'beat' if naive.wape and sel.wape and sel.wape < naive.wape else 'do not beat'} same weekday last week.",
            "",
            "### By demand class",
            "",
            "| Class | Selected WAPE | Moving average WAPE | Same weekday last week WAPE | Points |",
            "|---|---|---|---|---|",
        ]
        for klass, row in ev.by_class.items():
            lines.append(
                f"| {klass} | {pct(row['selected'].wape)} | {pct(row['moving_average_28'].wape)} | "
                f"{pct(row['seasonal_naive'].wape)} | {row['selected'].n} |"
            )
        worse = []
        for name, row in ev.by_category.items():
            a, b = row["selected"], row["moving_average_28"]
            if (
                a.wape is not None
                and b.wape is not None
                and a.total > 50
                and a.wape > b.wape * 1.01
            ):
                worse.append((name, a.wape, b.wape))
        lines += ["", "### Where the engine does not beat the baseline", ""]
        if worse:
            lines += ["| Category | Selected WAPE | Moving average WAPE |", "|---|---|---|"]
            lines += [
                f"| {n} | {pct(a)} | {pct(b)} |"
                for n, a, b in sorted(worse, key=lambda r: r[1] - r[2], reverse=True)
            ]
        else:
            lines.append("No category with enough volume is worse than the baseline.")
        e = ev.effects
        lines += [
            "",
            "### Event effects against the planted truth",
            "",
            f"{e['computed']} effects computed, {e['applied']} applied (festival and season effects together). "
            f"Festival effects only have a recorded truth. Against it: {e['tp']} real effects applied, "
            f"{e['fn']} real effects not applied, {e['fp']} applied where the festival truth is flat "
            f"(these can still be real seasonal or month start shifts that the truth table does not record), "
            f"{e['tn']} correctly left alone.",
        ]
        if e["median_relative_error"] is not None:
            lines.append(
                f"Median size error of the applied real effects, before shrinkage: "
                f"{e['median_relative_error'] * 100:.0f}%."
            )
        if e["strong_missed"]:
            lines += [
                "",
                "Strong planted effects the gate did not apply (too little volume to be sure):",
                "",
            ]
            lines += [f"- {k}, {c}: true multiplier {m:.2f}" for k, c, m in e["strong_missed"]]
        if with_lgbm and ev.lgbm:
            g = ev.lgbm
            gm, gs, gma = g["model"], g["statistical"], g["moving_average"]
            lines += [
                "",
                "### Global model (LightGBM)",
                "",
                f"Four weekly origins before the window, {g['objective']} objective, {g['trees']} trees, "
                f"{g['rows']:,} training rows. WAPE vs true demand: model {pct(gm.wape)}, statistical winner "
                f"{pct(gs.wape)}, moving average {pct(gma.wape)}. Bias: model {signed_pct(gm.bias)}.",
            ]
        lines.append("")
    lines += ["## What this shows", ""]
    for ev in evals:
        t = ev.by_method_true
        sel, base = t["selected"], t["moving_average_28"]
        obs = ev.by_method_observed["selected"]
        w, wo = ev.effect_days["with"], ev.effect_days["without"]
        gap = abs((obs.wape or 0) - (sel.wape or 0)) * 100
        lines.append(
            f"- {ev.name}: against true demand the selected methods score {pct(sel.wape)} and the "
            f"28 day average {pct(base.wape)}. Against observed sales on trusted days the selected "
            f"methods score {pct(obs.wape)}, so the app's own error number differs from the truth by "
            f"{gap:.1f} points."
        )
        if w.n:
            lines.append(
                f"  On the {w.n} product days where an event effect was applied, WAPE is "
                f"{pct(w.wape)} with the effects and {pct(wo.wape)} without them."
            )
    lines += [
        "",
        "Reading it: when demand is mostly noise, simple averages are hard to beat, and the parsimony "
        "rule keeps the moving average unless another method wins by 3 percent or more on earlier "
        "weeks. A method that won on earlier weeks can still lose on later ones. This report says so "
        "where it happens and does not tune the choice on the graded weeks. None of this proves "
        "anything about real shops. It shows how the method behaves against a known ground truth.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade forecasts against synthetic true demand")
    parser.add_argument(
        "--with-lgbm", action="store_true", help="also grade the global model (slow)"
    )
    parser.add_argument("--tenants", default="all")
    args = parser.parse_args()
    factory = get_session_factory()
    evals: list[TenantEval] = []
    with factory() as session:
        rows = session.execute(
            text("SELECT id, slug FROM tenants WHERE is_synthetic ORDER BY slug")
        ).all()
        for tid, slug in rows:
            if args.tenants != "all" and slug not in args.tenants.split(","):
                continue
            out(f"grading {slug}")
            evals.append(evaluate(session, tid, args.with_lgbm))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render(evals, args.with_lgbm), encoding="utf-8")
    out(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
