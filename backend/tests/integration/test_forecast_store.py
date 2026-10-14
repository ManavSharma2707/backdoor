"""Backtests, selections and effects survive a round trip through the database."""

from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.backtest import run_backtest
from app.engine.event_effects import EffectRecord
from app.engine.selection import select_methods
from app.models.intelligence import EventCategoryEffect, ForecastBacktest
from app.services import forecast_store as store
from tests import factories

START = date(2026, 1, 5)
AS_OF = date(2026, 7, 27)


def make_selection() -> tuple[object, list[str]]:
    n = 6
    rng = np.random.default_rng(8)
    shape = np.array([0.8, 0.9, 1.0, 1.0, 1.1, 1.4, 1.2])
    wd = (START.toordinal() - 1 + np.arange(203)) % 7
    y = rng.poisson(np.outer(rng.uniform(15, 30, n), shape[wd])).astype(np.float64)
    data = run_backtest(
        y_train=y,
        y_eval=y,
        multipliers=None,
        start=START,
        classes=["smooth"] * n,
        category_means=[None] * n,
    )
    keys = [f"p{i}" for i in range(n)]
    selection = select_methods(
        data, classes=["smooth"] * n, category_slugs=["a"] * n, product_keys=keys
    )
    return selection, keys


def test_model_version_is_created_once(db: Session) -> None:
    first = store.ensure_model_version(db)
    assert store.ensure_model_version(db) == first


def test_selection_round_trip(db: Session) -> None:
    tenant = factories.make_tenant(db)
    selection, keys = make_selection()
    run = store.create_run(
        db,
        tenant.id,
        kind="backtest",
        profile="full",
        as_of=AS_OF,
        horizon=28,
        config={"origins": 12},
    )
    rows = store.save_selection(db, tenant.id, run, selection)  # type: ignore[arg-type]
    store.finish_run(run, "succeeded")
    db.flush()
    assert rows == db.scalar(select(func.count()).select_from(ForecastBacktest))
    loaded = store.load_selection(db, tenant.id, AS_OF)
    assert loaded is not None
    again, stored_run = loaded
    assert stored_run.id == run.id
    assert set(again.segments) == set(selection.segments)  # type: ignore[attr-defined]
    seg, was = again.segments["a|smooth"], selection.segments["a|smooth"]  # type: ignore[attr-defined]
    assert (seg.selected, seg.selected_stat, seg.reason, seg.valid) == (
        was.selected,
        was.selected_stat,
        was.reason,
        was.valid,
    )
    assert seg.n_points == was.n_points
    assert seg.q_low == was.q_low
    assert set(seg.scores) == set(was.scores)
    assert seg.scores["moving_average"].mae == round(was.scores["moving_average"].mae, 4)
    assert again.classes["smooth"].selected == selection.classes["smooth"].selected  # type: ignore[attr-defined]
    assert set(again.products) == set(keys)
    assert again.products["p0"].method == selection.products["p0"].method  # type: ignore[attr-defined]
    assert again.products["p0"].rmse == round(selection.products["p0"].rmse, 4)  # type: ignore[attr-defined]
    assert set(again.tenant) == set(selection.tenant)  # type: ignore[attr-defined]
    assert again.n_origins == 12
    method, info = again.resolve("a|smooth", "smooth", allow_lgbm=False)
    assert info is again.segments["a|smooth"]
    assert method == seg.selected_stat


def test_selection_is_only_loaded_when_it_is_not_from_the_future(db: Session) -> None:
    tenant = factories.make_tenant(db)
    selection, _ = make_selection()
    run = store.create_run(
        db, tenant.id, kind="backtest", profile="full", as_of=AS_OF, horizon=28, config={}
    )
    store.save_selection(db, tenant.id, run, selection)  # type: ignore[arg-type]
    store.finish_run(run, "succeeded")
    db.flush()
    assert store.load_selection(db, tenant.id, date(2026, 7, 20)) is None
    assert store.load_selection(db, tenant.id, date(2026, 8, 3)) is not None
    failed = store.create_run(
        db,
        tenant.id,
        kind="backtest",
        profile="full",
        as_of=date(2026, 8, 3),
        horizon=28,
        config={},
    )
    store.finish_run(failed, "failed", "boom")
    db.flush()
    loaded = store.load_selection(db, tenant.id, date(2026, 8, 10))
    assert loaded is not None
    assert loaded[1].id == run.id  # a failed run is never reused
    assert store.selection_age_days(loaded[1], date(2026, 8, 10)) == 14


def test_no_stored_selection(db: Session) -> None:
    assert store.load_selection(db, factories.make_tenant(db).id, AS_OF) is None


def test_effects_replace_the_learned_rows_and_keep_configured_ones(db: Session) -> None:
    tenant = factories.make_tenant(db)
    category = factories.make_category(db, tenant)
    mapping = {"c": category.id}
    factories_effect = EventCategoryEffect(
        tenant_id=tenant.id,
        event_key="diwali",
        category_id=category.id,
        window="during",
        multiplier=1.25,
        origin="configured",
        n_occurrences=0,
        n_products=0,
        consistency=None,
        evidence={},
        confidence="low",
        is_applied=True,
    )
    db.add(factories_effect)
    db.flush()

    def record(mult: float, applied: bool) -> EffectRecord:
        return EffectRecord(
            "diwali", "c", "during", mult, "learned", 1, 5, 0.9, {"z_score": 4.1}, "medium", applied
        )

    assert store.save_effects(db, tenant.id, [record(1.8, True)], mapping) == 1
    assert store.save_effects(db, tenant.id, [record(1.6, False)], mapping) == 1
    rows = (
        db.execute(select(EventCategoryEffect).where(EventCategoryEffect.tenant_id == tenant.id))
        .scalars()
        .all()
    )
    assert sorted((r.origin, float(r.multiplier), r.is_applied) for r in rows) == [
        ("configured", 1.25, True),
        ("learned", 1.6, False),
    ]


def test_prune_keeps_the_newest_runs(db: Session) -> None:
    tenant = factories.make_tenant(db)
    selection, _ = make_selection()
    ids = []
    for week in range(5):
        run = store.create_run(
            db,
            tenant.id,
            kind="backtest",
            profile="full",
            as_of=date(2026, 7, 6) + timedelta(weeks=week),
            horizon=28,
            config={},
        )
        store.save_selection(db, tenant.id, run, selection)  # type: ignore[arg-type]
        store.finish_run(run, "succeeded")
        ids.append(run.id)
    store.prune_forecasts(db, tenant.id, keep=8, keep_backtests=2)
    left = set(db.scalars(select(ForecastBacktest.run_id).distinct()).all())
    assert left == set(ids[-2:])
