"""Stores and reloads what the engine learns: backtests, the method selection and effects.

The light profile does not back test. It reloads the newest stored selection and the learned
effects, so the numbers of a light run follow the last full run.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.timeutil import data_cutoff_for_week
from app.engine.backtest import Metrics
from app.engine.constants import ENGINE_VERSION, MODEL_NAME
from app.engine.event_effects import EffectRecord
from app.engine.selection import ProductScore, SegmentInfo, Selection
from app.models.intelligence import EventCategoryEffect, ForecastBacktest, ForecastRun
from app.models.reference import ModelVersion


def ensure_model_version(session: Session) -> uuid.UUID:
    """The `model_versions` row of this engine release, created on first use."""
    row = session.execute(
        select(ModelVersion.id).where(
            ModelVersion.name == MODEL_NAME, ModelVersion.version == ENGINE_VERSION
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    version = ModelVersion(
        name=MODEL_NAME, version=ENGINE_VERSION, notes="Statistical ladder and global model"
    )
    session.add(version)
    session.flush()
    return version.id


def create_run(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    kind: str,
    profile: str,
    as_of: date,
    horizon: int,
    config: dict[str, Any],
) -> ForecastRun:
    run = ForecastRun(
        tenant_id=tenant_id,
        kind=kind,
        profile=profile,
        data_cutoff=data_cutoff_for_week(as_of),
        as_of_date=as_of,
        horizon_days=horizon,
        model_version_id=ensure_model_version(session),
        config=config,
        status="running",
        started_at=now_utc(),
    )
    session.add(run)
    session.flush()
    return run


def finish_run(run: ForecastRun, status: str, error: str | None = None) -> None:
    run.status = status
    run.finished_at = now_utc()
    run.error = error


def _metrics_row(
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    scope: str,
    key: str,
    method: str,
    m: Metrics,
    n_folds: int,
    selected: bool,
    notes: dict[str, Any],
) -> ForecastBacktest:
    return ForecastBacktest(
        tenant_id=tenant_id,
        run_id=run_id,
        scope=scope,
        scope_key=key,
        method=method,
        n_folds=n_folds,
        n_points=m.n_points,
        mae=_dec(m.mae),
        wape=_dec(m.wape),
        bias=_dec(m.bias),
        rmse=_dec(m.rmse),
        coverage_ratio=_dec(m.coverage, 3),
        is_selected=selected,
        notes={**notes, "mean_actual": round(m.mean_actual, 4)},
    )


def _dec(value: float | None, places: int = 4) -> Any:
    if value is None:
        return None
    return round(min(max(value, -9999.0), 9999.0), places)


def save_selection(
    session: Session, tenant_id: uuid.UUID, run: ForecastRun, selection: Selection
) -> int:
    """Write every segment, class, tenant and product score of a backtest."""
    rows: list[ForecastBacktest] = []
    n = selection.n_origins
    for infos, scope in ((selection.segments, "segment"), (selection.classes, "tenant")):
        for info in infos.values():
            for method, m in info.scores.items():
                chosen = method == info.selected
                notes = info.notes() if chosen else {}
                rows.append(
                    _metrics_row(tenant_id, run.id, scope, info.key, method, m, n, chosen, notes)
                )
    for label, m in selection.tenant.items():
        name, _, scope_name = label.partition(":")
        rows.append(
            _metrics_row(
                tenant_id, run.id, "tenant", "overall", name, m, n, False, {"scope": scope_name}
            )
        )
    for key, score in selection.products.items():
        m = Metrics(
            score.n_points,
            score.mae,
            score.rmse,
            score.wape,
            None,
            score.mean_actual,
            score.coverage,
        )
        rows.append(_metrics_row(tenant_id, run.id, "product", key, score.method, m, n, True, {}))
    session.add_all(rows)
    session.flush()
    return len(rows)


def load_selection(
    session: Session, tenant_id: uuid.UUID, as_of: date
) -> tuple[Selection, ForecastRun] | None:
    """The newest successful backtest whose data cutoff is not after the plan date."""
    run = session.execute(
        select(ForecastRun)
        .where(
            ForecastRun.tenant_id == tenant_id,
            ForecastRun.kind == "backtest",
            ForecastRun.status == "succeeded",
            ForecastRun.as_of_date <= as_of,
        )
        .order_by(ForecastRun.as_of_date.desc(), ForecastRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    rows = list(
        session.execute(
            select(ForecastBacktest).where(
                ForecastBacktest.tenant_id == tenant_id, ForecastBacktest.run_id == run.id
            )
        ).scalars()
    )
    segments: dict[str, SegmentInfo] = {}
    classes: dict[str, SegmentInfo] = {}
    products: dict[str, ProductScore] = {}
    tenant: dict[str, Metrics] = {}
    n_origins = 0

    def metrics_of(row: ForecastBacktest) -> Metrics:
        mean_actual = float((row.notes or {}).get("mean_actual", 0.0))
        return Metrics(
            row.n_points,
            float(row.mae),
            float(row.rmse),
            float(row.wape) if row.wape is not None else None,
            float(row.bias) if row.bias is not None else None,
            mean_actual,
            float(row.coverage_ratio),
        )

    for row in rows:
        n_origins = max(n_origins, int(row.n_folds))
        m = metrics_of(row)
        if row.scope == "product":
            products[row.scope_key] = ProductScore(
                row.method, m.n_points, m.mae, m.rmse, m.wape, m.mean_actual, m.coverage
            )
        elif row.scope == "tenant" and row.scope_key == "overall":
            tenant[f"{row.method}:{(row.notes or {}).get('scope', 'all')}"] = m
        elif row.scope in ("segment", "tenant"):
            table = segments if row.scope == "segment" else classes
            key = row.scope_key
            klass = key.split("|")[1] if row.scope == "segment" else key.removeprefix("class:")
            info = table.setdefault(
                key,
                SegmentInfo(key, klass, "moving_average", "moving_average", "default", 0, 0, False),
            )
            info.scores[row.method] = m
            if row.is_selected and row.notes:
                info.selected = str(row.notes["selected"])
                info.selected_stat = str(row.notes["selected_stat"])
                info.reason = str(row.notes["reason"])
                info.n_products = int(row.notes["n_products"])
                info.valid = bool(row.notes["valid"])
                info.q_low = float(row.notes["q_low"])
                info.q_high = float(row.notes["q_high"])
                info.mean_level = float(row.notes["mean_level"])
    for info in [*segments.values(), *classes.values()]:
        anchor = info.scores.get("moving_average")
        info.n_points = anchor.n_points if anchor else 0
    key_by_class = {k.removeprefix("class:"): v for k, v in classes.items()}
    return Selection(segments, key_by_class, products, tenant, n_origins or 12), run


def selection_age_days(run: ForecastRun, as_of: date) -> int:
    return (as_of - run.as_of_date).days


def save_effects(
    session: Session,
    tenant_id: uuid.UUID,
    records: list[EffectRecord],
    category_by_key: dict[str, uuid.UUID],
    computed_at: datetime | None = None,
) -> int:
    """Replace the learned effects of a tenant. Owner set (configured) rows are left alone."""
    session.execute(
        delete(EventCategoryEffect).where(
            EventCategoryEffect.tenant_id == tenant_id, EventCategoryEffect.origin == "learned"
        )
    )
    stamp = computed_at or now_utc()
    rows = [
        EventCategoryEffect(
            tenant_id=tenant_id,
            event_key=r.event_key,
            category_id=category_by_key[r.category_key],
            window=r.window,
            multiplier=r.multiplier,
            origin="learned",
            n_occurrences=r.n_occurrences,
            n_products=r.n_products,
            consistency=r.consistency,
            evidence=r.evidence,
            confidence=r.confidence,
            is_applied=r.is_applied,
            computed_at=stamp,
        )
        for r in records
        if r.origin == "learned"
    ]
    session.add_all(rows)
    session.flush()
    return len(rows)


def prune_forecasts(session: Session, tenant_id: uuid.UUID, keep: int, keep_backtests: int) -> None:
    """Keep the newest `keep` weekly runs' values and `keep_backtests` backtest runs."""
    session.execute(
        text(
            """
            DELETE FROM forecast_values WHERE tenant_id = :t AND run_id NOT IN (
                SELECT id FROM forecast_runs WHERE tenant_id = :t AND kind = 'weekly'
                ORDER BY as_of_date DESC, started_at DESC LIMIT :keep)
            """
        ),
        {"t": tenant_id, "keep": keep},
    )
    session.execute(
        text(
            """
            DELETE FROM forecast_backtests WHERE tenant_id = :t AND run_id NOT IN (
                SELECT id FROM forecast_runs WHERE tenant_id = :t AND kind = 'backtest'
                ORDER BY as_of_date DESC, started_at DESC LIMIT :keep)
            """
        ),
        {"t": tenant_id, "keep": keep_backtests},
    )


def effects_age(newest: datetime | None, now: datetime) -> timedelta | None:
    return None if newest is None else now - newest
