"""The read only half of the Monday pipeline: load, learn, forecast and plan.

`compute_plan` writes nothing, so it serves the real pipeline (which persists the outcome), the
backfill and the what if runs (which never do). The caller decides what to store.
"""

import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.logging import get_logger
from app.engine import dq
from app.engine.backtest import BacktestData, run_backtest
from app.engine.calendar import CalendarEvent
from app.engine.constants import (
    EFFECT_REFRESH_DAYS,
    FORECAST_HORIZON_DAYS,
    LGBM_TIME_CAP_SECONDS,
    SELECTION_MAX_AGE_DAYS,
)
from app.engine.deadstock import abc_classes
from app.engine.demand_class import DemandProfile, classify_demand
from app.engine.event_effects import (
    EffectRecord,
    PromoOccurrence,
    effective_records,
    learn_event_effects,
    learn_promotion_effects,
)
from app.engine.forecast import (
    ProductForecast,
    TrainingData,
    adjust_for_effects,
    category_means,
    censored_share,
    effect_matrices,
    forecast_products,
    training_data,
)
from app.engine.inputs import ProductInfo, SettingsInfo, SupplierInfo
from app.engine.plan import Overrides, PlanContext, PlanResult, ProductSignals, build_plan
from app.engine.selection import Selection, select_methods
from app.models.intelligence import ForecastRun
from app.services import dq_service, forecast_store
from app.services.plan_data import History, PlanLoader, TenantInfo

log = get_logger(__name__)

PRE_PLAN_CODES = (
    "MISSING_SUPPLIER",
    "MISSING_COST",
    "MISSING_LEAD_TIME",
    "MISSING_EXPIRY",
    "STALE_STOCK_COUNT",
    "PRICE_ANOMALY",
    "NEW_PRODUCT",
    "SPARSE_HISTORY",
    "CENSORED_HISTORY",
)


@dataclass
class ComputeResult:
    tenant: TenantInfo
    settings: SettingsInfo
    as_of: date
    profile: str
    history: History
    training: TrainingData
    products: list[ProductInfo]
    profiles: list[DemandProfile]
    suppliers: dict[uuid.UUID, SupplierInfo]
    events: list[CalendarEvent]
    effects: list[EffectRecord]
    effects_fresh: bool
    selection: Selection
    selection_source: str
    selection_run: ForecastRun | None
    backtest: BacktestData | None
    forecasts: list[ProductForecast]
    plan: PlanResult
    findings: list[dq.DqFinding]
    category_ids: dict[str, uuid.UUID]
    promotions: list[PromoOccurrence]
    abc: dict[uuid.UUID, str]
    global_model: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _sellable_window(events: list[CalendarEvent], as_of: date) -> bool:
    horizon = as_of + timedelta(days=60)
    return any(e.anchor <= horizon and e.last_day >= as_of for e in events)


def compute_plan(
    session: Session,
    tenant_id: uuid.UUID,
    as_of: date,
    profile: str,
    *,
    overrides: Overrides | None = None,
    live: bool = True,
    force_backtest: bool = False,
    forecast_run_id: uuid.UUID | None = None,
    stop: Callable[[], bool] | None = None,
) -> ComputeResult:
    """Everything a plan needs, as of the data cutoff `as_of` (the Monday).

    `live` is true for the current week: it adds the checks on the cached stock balances, which
    only describe now and make no sense for a plan of a past week. With `forecast_run_id` the
    stored forecasts, effects and selection of that run are reused and nothing is learned (what if
    runs).
    """
    timings: dict[str, float] = {}
    notes: list[str] = []
    lap = time.monotonic()

    def tick(name: str) -> None:
        nonlocal lap
        timings[name] = round(time.monotonic() - lap, 2)
        lap = time.monotonic()

    loader = PlanLoader(session, tenant_id, as_of)
    tenant = loader.tenant()
    settings = loader.settings()
    suppliers = loader.suppliers()
    history = loader.history()
    all_products = loader.products(history, suppliers)
    by_id = {p.id: p for p in all_products}
    products = [by_id[pid] for pid in history.product_ids]
    events = loader.calendar_events()
    tick("load")

    horizon = settings.forecast_horizon_days or FORECAST_HORIZON_DAYS
    training = training_data(
        history.units, history.codes, history.promo, history.start, settings.censor_policy
    )
    n_products, n_days = training.trusted.shape
    profiles = [classify_demand(training.trusted[i]) for i in range(n_products)]
    classes = [p.demand_class for p in profiles]
    category_keys = sorted({str(p.category_id) for p in products})
    code_of = {k: i for i, k in enumerate(category_keys)}
    codes = np.array([code_of[str(p.category_id)] for p in products], dtype=np.int64)
    slugs = [p.category_slug for p in products]
    category_ids = {str(p.category_id): p.category_id for p in products}
    promotions = loader.promotions(
        history.index, {p.category_id: str(p.category_id) for p in products}
    )
    is_medical = tenant.business_type == "medical"
    product_keys = [str(p.id) for p in products]
    eligible = np.array([c not in ("new", "no_history") for c in classes])
    cat_mean = category_means(training.trusted, codes, len(category_keys), eligible)
    cat_means = [None if np.isnan(cat_mean[c]) else float(cat_mean[c]) for c in codes]
    tick("prepare")

    # ---- effects: learn on a full run or when the stored ones are old, else reuse
    stored, newest = loader.stored_effects()
    stale = newest is None or (now_utc() - newest).days >= EFFECT_REFRESH_DAYS
    fresh_effects = (profile == "full" or stale or not live) and forecast_run_id is None
    if fresh_effects:
        learned = learn_event_effects(
            events=events,
            y=training.trusted,
            start=history.start,
            category_codes=codes,
            category_keys=category_keys,
            is_medical=is_medical,
        )
        learned += learn_promotion_effects(
            promotions=promotions,
            y_baseline=training.trusted,
            y_actual=training.with_promo,
            start=history.start,
            category_codes=codes,
            category_keys=category_keys,
            events=events,
            is_medical=is_medical,
        )
        configured = [e for e in stored if e.origin == "configured"]
        effects = learned + configured
    else:
        effects = stored
    applied = list(effective_records(effects).values())
    mult, event_keys = effect_matrices(
        applied,
        events,
        category_keys=category_keys,
        category_codes=codes,
        promotions=promotions,
        start=history.start,
        n_days=n_days + horizon,
    )
    adjusted = adjust_for_effects(training.trusted, mult[:, :n_days])
    tick("effects")

    # ---- selection: fresh backtest on a full run, else the stored selection
    backtest: BacktestData | None = None
    selection_run: ForecastRun | None = None
    selection_source = "stored"
    global_forecast: np.ndarray | None = None
    global_info: dict[str, Any] = {}
    stored_selection = (
        None
        if (force_backtest or profile == "full") and forecast_run_id is None
        else forecast_store.load_selection(session, tenant_id, as_of)
    )
    if stored_selection is not None:
        selection, selection_run = stored_selection
        age = forecast_store.selection_age_days(selection_run, as_of)
        if age > SELECTION_MAX_AGE_DAYS:
            notes.append(f"The stored method selection is {age} days old.")
            selection_source = "stored_old"
    else:
        selection_source = "fresh"
        backtest, selection, global_forecast, global_info = _backtest(
            training,
            history,
            events,
            promotions,
            codes,
            category_keys,
            slugs,
            classes,
            cat_means,
            product_keys,
            settings,
            is_medical,
            profile,
            horizon,
            stop,
            tick_effects=tick,
        )
    tick("selection")

    allow_global = profile == "full" and global_forecast is not None
    if forecast_run_id is not None:
        forecasts = stored_forecasts(
            session,
            tenant_id,
            forecast_run_id,
            history.product_ids,
            classes,
            slugs,
            selection,
            as_of,
            horizon,
        )
    else:
        forecasts = forecast_products(
            y_adjusted=adjusted,
            start=history.start,
            as_of=as_of,
            horizon=horizon,
            classes=classes,
            category_keys=category_keys,
            category_slugs=slugs,
            category_means=cat_means,
            selection=selection,
            multipliers=mult,
            event_keys=event_keys,
            global_forecast=global_forecast,
            allow_global=allow_global,
        )
    tick("forecast")

    # ---- data quality and the plan
    revenue_90 = {
        pid: float(history.revenue[i, -90:].sum()) for i, pid in enumerate(history.product_ids)
    }
    abc = abc_classes(revenue_90)
    labels = {p.id: f"{p.name} ({p.sku})" for p in products}
    findings = pre_findings(
        session,
        tenant_id,
        as_of,
        products,
        suppliers,
        settings,
        abc,
        training,
        history,
        events,
        live,
        labels,
    )
    pre_by_product: dict[str, list[str]] = defaultdict(list)
    for f in findings:
        if f.entity_type == "product" and f.entity_id and f.code in PRE_PLAN_CODES:
            pre_by_product[str(f.entity_id)].append(f.code)
    signals = _signals(
        products, profiles, training, history, abc, promotions, category_ids, as_of, horizon
    )
    promo_applied = {r.category_key for r in applied if r.event_key == "promotion"}
    unknown = frozenset({k for k in category_keys if k not in promo_applied})
    ctx = PlanContext(
        as_of=as_of,
        settings=settings,
        suppliers=suppliers,
        events=events,
        selection=selection,
        horizon=horizon,
        in_season=_sellable_window(events, as_of),
        global_model_failed=profile == "full" and global_forecast is None,
        overrides=overrides or Overrides(),
        promo_unknown_categories=unknown,
    )
    plan = build_plan(products, forecasts, signals, ctx, pre_by_product)
    findings += _plan_findings(plan)
    tick("plan")
    return ComputeResult(
        tenant=tenant,
        settings=settings,
        as_of=as_of,
        profile=profile,
        history=history,
        training=training,
        products=products,
        profiles=profiles,
        suppliers=suppliers,
        events=events,
        effects=effects,
        effects_fresh=fresh_effects,
        selection=selection,
        selection_source=selection_source,
        selection_run=selection_run,
        backtest=backtest,
        forecasts=forecasts,
        plan=plan,
        findings=findings,
        category_ids=category_ids,
        promotions=promotions,
        abc=abc,
        global_model=global_info,
        timings=timings,
        notes=notes,
    )


def stored_forecasts(
    session: Session,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    product_ids: list[uuid.UUID],
    classes: list[Any],
    slugs: list[str],
    selection: Selection,
    as_of: date,
    horizon: int,
) -> list[ProductForecast]:
    """Forecasts of an earlier run, read back from `forecast_values`."""
    rows = session.execute(
        text(
            """
            SELECT product_id, forecast_date, yhat, yhat_lower, yhat_upper, method,
                   event_multiplier, event_key
            FROM forecast_values WHERE tenant_id = :t AND run_id = :r ORDER BY product_id,
                 forecast_date
            """
        ),
        {"t": tenant_id, "r": run_id},
    ).all()
    by_product: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for r in rows:
        by_product[r[0]].append(r)
    out: list[ProductForecast] = []
    for pid, klass, slug in zip(product_ids, classes, slugs, strict=True):
        series = by_product.get(pid, [])[:horizon]
        yhat = np.array([float(r[2]) for r in series] or [0.0] * horizon)
        mult = np.array([float(r[6]) for r in series] or [1.0] * horizon)
        key = f"{slug}|{klass}"
        _, info = selection.resolve(key, klass, allow_lgbm=False)
        out.append(
            ProductForecast(
                method=series[0][5] if series else "moving_average",
                yhat=yhat,
                lower=np.array([float(r[3]) for r in series] or [0.0] * horizon),
                upper=np.array([float(r[4]) for r in series] or [0.0] * horizon),
                base=np.divide(yhat, mult, out=yhat.copy(), where=mult > 0),
                multiplier=mult,
                event_keys=[r[7] for r in series] or [None] * horizon,
                segment=key if klass in ("smooth", "erratic", "intermittent", "lumpy") else None,
                interval=info,
            )
        )
    return out


def _backtest(
    training: TrainingData,
    history: History,
    events: list[CalendarEvent],
    promotions: list[PromoOccurrence],
    codes: np.ndarray,
    category_keys: list[str],
    slugs: list[str],
    classes: list[Any],
    cat_means: list[float | None],
    product_keys: list[str],
    settings: SettingsInfo,
    is_medical: bool,
    profile: str,
    horizon: int,
    stop: Callable[[], bool] | None,
    tick_effects: Callable[[str], None],
) -> tuple[BacktestData, Selection, np.ndarray | None, dict[str, Any]]:
    """Back test the statistical ladder (and the global model on a full run).

    The effects used inside the backtest are learned from the days before its first origin, so no
    forecast ever sees a festival that happened after the origin it is scored at.
    """
    n_origins = settings.backtest_origins
    n_days = training.n_days
    cut = n_days - 7 * n_origins
    effects_cut = learn_event_effects(
        events=events,
        y=training.trusted[:, :cut],
        start=history.start,
        category_codes=codes,
        category_keys=category_keys,
        is_medical=is_medical,
    )
    applied = list(effective_records(effects_cut).values())
    mult, _ = effect_matrices(
        applied,
        events,
        category_keys=category_keys,
        category_codes=codes,
        promotions=[],
        start=history.start,
        n_days=n_days + 7,
    )
    adjusted = training.trusted / mult[:, :n_days]
    observed = np.where(training.fill_used, np.nan, training.trusted)
    global_forecast: np.ndarray | None = None
    info: dict[str, Any] = {}
    extra: dict[str, dict[tuple[int, int], np.ndarray]] = {}
    if profile == "full":
        try:
            result = _global_model(training, history, events, codes, horizon, stop)
            extra["lightgbm_global"] = result.backtest
            global_forecast = result.forecast
            info = {
                "objective": result.objective,
                "rows": result.n_rows,
                "trees": result.n_trees,
                "validation_mae": result.validation_mae,
            }
        except Exception as exc:
            log.warning("global_model.skipped", reason=str(exc))
            info = {"skipped": str(exc)}
    data = run_backtest(
        y_train=adjusted,
        y_eval=observed,
        multipliers=mult,
        start=history.start,
        classes=classes,
        category_means=cat_means,
        n_origins=n_origins,
        extra=extra or None,
    )
    selection = select_methods(
        data,
        classes=classes,
        category_slugs=slugs,
        product_keys=product_keys,
        with_lgbm=bool(extra),
    )
    tick_effects("backtest")
    return data, selection, global_forecast, info


def _global_model(
    training: TrainingData,
    history: History,
    events: list[CalendarEvent],
    codes: np.ndarray,
    horizon: int,
    stop: Callable[[], bool] | None,
) -> Any:
    from app.engine.features import FeatureBuilder, FeatureInputs, price_ratio_matrix
    from app.engine.methods.lgbm import run_global_model

    n_products, n_days = training.trusted.shape
    promo = np.zeros((n_products, n_days + horizon), dtype=bool)
    promo[:, :n_days] = history.promo
    inputs = FeatureInputs(
        y=training.trusted,
        start=history.start,
        category_codes=codes,
        promo=promo,
        price_ratio=price_ratio_matrix(history.units, history.revenue),
        events=events,
        horizon=horizon,
    )
    started = time.monotonic()

    def time_cap() -> bool:
        return (stop is not None and stop()) or time.monotonic() - started > LGBM_TIME_CAP_SECONDS

    return run_global_model(FeatureBuilder(inputs), horizon=horizon, stop=time_cap)


def _signals(
    products: list[ProductInfo],
    profiles: list[DemandProfile],
    training: TrainingData,
    history: History,
    abc: dict[uuid.UUID, str],
    promotions: list[PromoOccurrence],
    category_ids: dict[str, uuid.UUID],
    as_of: date,
    horizon: int,
) -> list[ProductSignals]:
    shares = censored_share(training.censored)
    available = history.codes == 0
    out: list[ProductSignals] = []
    last90 = training.trusted[:, -90:]
    trusted90 = (~np.isnan(last90)).mean(axis=1) if last90.shape[1] else np.zeros(len(products))
    category_promos: dict[str, int] = defaultdict(int)
    product_promos: dict[int, int] = defaultdict(int)
    end = as_of + timedelta(days=horizon)
    for pr in promotions:
        if pr.end >= as_of and pr.start < end:
            if pr.product_index is not None:
                product_promos[pr.product_index] += 1
            elif pr.category_key:
                category_promos[pr.category_key] += 1
    for i, p in enumerate(products):
        window = training.trusted[i, -56:]
        valid = window[~np.isnan(window)]
        out.append(
            ProductSignals(
                profile=profiles[i],
                demand=history.units[i],
                available=available[i],
                trusted_share_90=float(trusted90[i]),
                censored_share_56=float(shares[i]),
                demand_std_56=float(valid.std()) if valid.size else 0.0,
                start=history.start,
                abc=abc.get(p.id, "C"),
                promotions_in_horizon=product_promos.get(i, 0)
                + category_promos.get(str(p.category_id), 0),
            )
        )
    return out


def pre_findings(
    session: Session,
    tenant_id: uuid.UUID,
    as_of: date,
    products: list[ProductInfo],
    suppliers: dict[uuid.UUID, SupplierInfo],
    settings: SettingsInfo,
    abc: dict[uuid.UUID, str],
    training: TrainingData,
    history: History,
    events: list[CalendarEvent],
    live: bool,
    labels: dict[uuid.UUID, str],
) -> list[dq.DqFinding]:
    findings = dq.check_catalogue(products, suppliers, settings, abc, as_of)
    facts = {
        pid: dq.HistoryFacts(
            trusted_days=int((~np.isnan(training.trusted[i, -180:])).sum()),
            censored_share=float(training.censored[i, -56:].mean())
            if training.censored.shape[1]
            else 0.0,
        )
        for i, pid in enumerate(history.product_ids)
    }
    findings += dq.check_history(products, facts, as_of, settings.nonmoving_days)
    names = {sid: s.name for sid, s in suppliers.items()}
    findings += dq_service.purchasing_findings(session, tenant_id, as_of, products, names)
    findings += dq_service.duplicate_findings(session, tenant_id, as_of)
    findings += dq_service.unrecorded_stockout_findings(session, tenant_id, as_of, labels)
    findings += dq.check_calendar(events, as_of)
    if live:
        findings += dq_service.stock_findings(session, tenant_id, labels)
    return findings


def _plan_findings(plan: PlanResult) -> list[dq.DqFinding]:
    out: list[dq.DqFinding] = []
    for ln in plan.lines:
        p = ln.product
        label = f"{p.name} ({p.sku})"
        if "ZERO_SALES_UNVERIFIED" in ln.warnings:
            out.append(
                dq.finding(
                    "ZERO_SALES_UNVERIFIED",
                    f"{p.name} had no sales, but it was not on the shelf for much of the last "
                    f"{plan.settings.nonmoving_days} days. Check it before calling it dead stock.",
                    "Count the stock and record the out of stock periods.",
                    entity_type="product",
                    entity_id=p.id,
                    entity_label=label,
                )
            )
        if "MOQ_VS_SHELF_LIFE" in ln.warnings:
            out.append(
                dq.finding(
                    "MOQ_VS_SHELF_LIFE",
                    f"The minimum order for {p.name} is more than it can sell before it expires.",
                    "Ask the supplier for a smaller minimum or a longer shelf life.",
                    entity_type="product",
                    entity_id=p.id,
                    entity_label=label,
                )
            )
        if "PROMO_UPLIFT_UNKNOWN" in ln.warnings:
            out.append(
                dq.finding(
                    "PROMO_UPLIFT_UNKNOWN",
                    f"A promotion is planned for {p.name} and we have no history to "
                    "estimate its effect.",
                    "Record how a promotion went the next time, so the effect can be learned.",
                    entity_type="product",
                    entity_id=p.id,
                    entity_label=label,
                )
            )
    return out


def decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
