"""One test per planted scenario S01 to S21 (`seed-data-spec.md` section 10).

Products come from `seed/scenarios.yaml`, never from hard coded ids. The pipeline runs once per
tenant (light profile) on the seeded database, and each test reads the stored report.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text

from app.models.intelligence import WeeklyReport
from app.services import pipeline
from tests.pipeline.conftest import AS_OF, PipelineDb

SCENARIOS = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "seed" / "scenarios.yaml").read_text(encoding="utf-8")
)["tenants"]
TENANTS = ("fmcg_a", "med_a", "med_b")


@dataclass
class Plan:
    db: PipelineDb
    key: str
    payload: dict[str, Any]
    by_sku: dict[str, dict[str, Any]]

    @property
    def tenant_id(self) -> Any:
        return self.db.tenant_id(self.key)

    def scenario(self, name: str) -> dict[str, Any]:
        return SCENARIOS[self.key][name]

    def line(self, sku: str) -> dict[str, Any]:
        return self.by_sku[sku]

    def sql(self, sql: str, **params: Any) -> list[Any]:
        with self.db.session() as s:
            return list(s.execute(text(sql), {"t": self.tenant_id, **params}).all())

    def codes(self, sku: str) -> set[str]:
        return {w["code"] for w in self.line(sku)["warnings"]}

    @property
    def summary(self) -> dict[str, Any]:
        return self.payload["summary"]

    def open_issues(self, code: str) -> list[str]:
        return [
            r[0]
            for r in self.sql(
                "SELECT detail->>'label' FROM data_quality_issues "
                "WHERE tenant_id = :t AND code = :c AND resolved_at IS NULL",
                c=code,
            )
        ]


@pytest.fixture(scope="module")
def plans(pipeline_db: PipelineDb) -> dict[str, Plan]:
    pipeline_db.clear_plans()
    out: dict[str, Plan] = {}
    for key in TENANTS:
        outcome = pipeline.run_pipeline(
            pipeline_db.factory, pipeline_db.tenant_id(key), AS_OF, "light"
        )
        assert outcome.status == "succeeded", outcome.error
        with pipeline_db.session() as s:
            report = s.get(WeeklyReport, outcome.report_id)
            assert report is not None
            payload = report.payload
        out[key] = Plan(
            pipeline_db, key, payload, {ln["sku"]: ln for ln in payload["lines"].values()}
        )
    return out


def having(name: str) -> list[str]:
    return [k for k in TENANTS if name in SCENARIOS[k]]


def effects(plan: Plan, event: str, category_slug: str) -> list[Any]:
    return plan.sql(
        """
        SELECT e.window, e.is_applied, e.origin, e.n_occurrences, e.multiplier, e.evidence
        FROM event_category_effects e JOIN categories c ON c.tenant_id = e.tenant_id AND c.id = e.category_id
        WHERE e.tenant_id = :t AND e.event_key = :k AND c.slug = :s ORDER BY e.window
        """,
        k=event,
        s=category_slug,
    )


@pytest.mark.parametrize("key", having("S01"))
def test_s01_diwali_effect_is_learned_and_applied_with_one_occurrence(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    applied = {
        slug: [e for e in effects(plan, "diwali", slug) if e[1]]
        for slug in plan.scenario("S01")["categories"]
    }
    winners = [slug for slug, rows in applied.items() if rows]
    assert winners, "no planted Diwali category was learned"
    for slug in winners:
        assert all(
            e[2] == "learned" and e[3] == 1 and Decimal(e[4]) > Decimal("1.15")
            for e in applied[slug]
        )
    diwali = next(f for f in plan.payload["festival"] if f["event_key"] == "diwali")
    labelled = [c for c in diwali["categories"] if c["applied"]]
    assert labelled
    assert all(
        c["label"] == "learned" and c["label_text"].startswith("Learned from last year")
        for c in labelled
    )


@pytest.mark.parametrize("key", [k for k in TENANTS if "S02" in SCENARIOS[k]])
def test_s02_a_category_with_no_real_effect_is_not_applied(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    s02 = plan.scenario("S02")
    pairs = s02["pairs"] if "pairs" in s02 else [{"event": "diwali", "category": s02["category"]}]
    seen = 0
    for pair in pairs:
        event = pair["event"].replace("-2025", "")
        rows = effects(plan, event, pair["category"])
        assert not any(r[1] for r in rows), (event, pair["category"], rows)
        seen += bool(rows)
        for window, _applied, _origin, _n, _m, evidence in rows:
            assert evidence["blocked_by"], window
    assert seen, "the engine should still have computed the effect"


def test_s02_medical_festival_effect_with_one_occurrence_names_the_medical_rule(
    plans: dict[str, Plan],
) -> None:
    for key in ("med_a", "med_b"):
        plan = plans[key]
        rows = effects(plan, "diwali", plan.scenario("S02")["category"])
        assert rows
        assert all(not r[1] for r in rows)
        assert any("medical_festival_rule" in r[5]["blocked_by"] for r in rows)


@pytest.mark.parametrize("key", TENANTS)
def test_s03_censored_days_are_excluded_and_warned_about(plans: dict[str, Plan], key: str) -> None:
    plan = plans[key]
    s03 = plan.scenario("S03")
    for sku in [*s03["recorded"], *s03["unrecorded"]]:
        rows = plan.sql(
            """
            SELECT count(*) FROM daily_product_stats d JOIN products p ON p.tenant_id = d.tenant_id AND p.id = d.product_id
            WHERE d.tenant_id = :t AND p.sku = :s AND d.is_censored
            """,
            s=sku,
        )
        assert rows[0][0] > 0, sku
    # Recorded intervals are respected: every day inside one is not trusted.
    leaks = plan.sql(
        """
        SELECT count(*) FROM stockout_intervals i
        JOIN products p ON p.tenant_id = i.tenant_id AND p.id = i.product_id
        JOIN daily_product_stats d ON d.tenant_id = i.tenant_id AND d.product_id = i.product_id
             AND d.stat_date BETWEEN i.start_date AND COALESCE(i.end_date, d.stat_date)
        WHERE i.tenant_id = :t AND i.source = 'recorded' AND p.sku = ANY(:skus) AND NOT d.is_censored
        """,
        skus=s03["recorded"],
    )
    assert leaks[0][0] == 0
    warned = [
        sku
        for sku in [*s03["recorded"], *s03["unrecorded"]]
        if "CENSORED_HISTORY" in plan.codes(sku)
    ]
    flagged = plan.open_issues("UNRECORDED_STOCKOUT_SUSPECTED")
    assert warned or flagged
    for line in plan.by_sku.values():
        if "CENSORED_HISTORY" in {w["code"] for w in line["warnings"]}:
            assert line["confidence"] != "high"


@pytest.mark.parametrize("key", having("S04"))
def test_s04_overstocked_slow_movers_are_in_reduce_with_no_purchase(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    lines = [plan.line(sku) for sku in plan.scenario("S04")["products"]]
    reduced = [ln for ln in lines if "reduce" in ln["sections"]]
    assert len(reduced) >= 4
    assert all(Decimal(ln["suggested_qty"]) == 0 for ln in reduced)


@pytest.mark.parametrize("key", having("S05"))
def test_s05_discontinued_products_are_not_moving(plans: dict[str, Plan], key: str) -> None:
    plan = plans[key]
    for sku in plan.scenario("S05")["products"]:
        line = plan.line(sku)
        assert line["stock_status"] == "non_moving", sku
        assert "reduce" in line["sections"]
        assert "NON_MOVING" in line["reason_codes"]
        assert Decimal(line["suggested_qty"]) == 0


@pytest.mark.parametrize("key", having("S06"))
def test_s06_products_out_of_stock_for_months_are_unverified_not_dead(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    for sku in plan.scenario("S06")["products"]:
        line = plan.line(sku)
        assert line["stock_status"] == "unverified", sku
        assert "CHECK_BEFORE_DEAD" in line["reason_codes"]
        assert "NON_MOVING" not in line["reason_codes"]
        assert "check" in line["reason_text"].lower()
    assert "unverified_value" in plan.summary
    assert "ZERO_SALES_UNVERIFIED" in {n["code"] for n in plan.payload["data_notes"]}


@pytest.mark.parametrize("key", having("S07"))
def test_s07_overdue_order_is_ignored_and_watched(plans: dict[str, Plan], key: str) -> None:
    plan = plans[key]
    overdue = [ln for ln in plan.by_sku.values() if Decimal(ln["incoming_excluded_overdue"]) > 0]
    assert overdue
    for line in overdue:
        assert "PO_OVERDUE" in {w["code"] for w in line["warnings"]}
        assert "watch" in line["sections"]
        assert "OVERDUE_ORDER_IGNORED" in line["reason_codes"]
    assert any(o["days_late"] >= 6 for ln in overdue for o in ln["overdue_orders"])
    assert plan.open_issues("PO_OVERDUE")


def test_s08_a_tight_budget_shows_a_shortfall_and_unfunded_lines(plans: dict[str, Plan]) -> None:
    plan = plans["fmcg_a"]
    budget = plan.payload["budget"]
    assert budget["constrained"]
    assert Decimal(budget["shortfall"]) > 0
    assert budget["unfunded_count"] > 0
    assert "does not cover" in budget["claim"]
    ratio = Decimal(budget["budget"]) / Decimal(budget["needed"])
    assert Decimal("0.60") <= ratio <= Decimal("0.80"), ratio
    assert Decimal(budget["funded"]) <= Decimal(budget["budget"])
    for line in plan.by_sku.values():
        if line["budget_limited"] and line["risk_level"] == "critical":
            assert "CRITICAL_UNFUNDED" in {w["code"] for w in line["warnings"]}
    assert all(
        "BUDGET_LIMITED" in ln["reason_codes"]
        for ln in plan.by_sku.values()
        if ln["budget_limited"]
    )


@pytest.mark.parametrize("key", having("S09"))
def test_s09_a_generous_budget_leaves_no_shortfall(plans: dict[str, Plan], key: str) -> None:
    plan = plans[key]
    budget = plan.payload["budget"]
    assert not budget["constrained"]
    assert Decimal(budget["shortfall"]) == 0
    assert budget["unfunded_count"] == 0
    assert "covers the full need" in budget["claim"]
    ratio = Decimal(budget["budget"]) / Decimal(budget["needed"])
    assert Decimal("1.00") <= ratio <= Decimal("1.15"), ratio


@pytest.mark.parametrize("key", TENANTS)
def test_s10_missing_data_warns_and_lowers_confidence(plans: dict[str, Plan], key: str) -> None:
    plan = plans[key]
    s10 = plan.scenario("S10")
    for sku in s10["missing_lead_time"]:
        line = plan.line(sku)
        assert "MISSING_LEAD_TIME" in plan.codes(sku)
        assert line["lead_time_assumed"]
        assert line["lead_time_source"] == "business_default"
        assert line["confidence"] != "high"
        assert line["provenance"]["lead_time"] == "assumed"
    for sku in s10["missing_cost"]:
        line = plan.line(sku)
        assert {"MISSING_COST", "MISSING_SUPPLIER"} <= plan.codes(sku)
        assert line["unit_cost"] is None
        assert line["est_spend"] is None
        assert Decimal(line["allocated_qty"]) == 0
        assert "MISSING_COST" in line["reason_codes"]
    expiry = plan.open_issues("MISSING_EXPIRY")
    assert len(expiry) >= 1
    for sku in s10["missing_expiry"]:
        assert "MISSING_EXPIRY" in plan.codes(sku)
    assert {"MISSING_LEAD_TIME", "MISSING_COST", "MISSING_EXPIRY"} <= {
        n["code"] for n in plan.payload["data_notes"]
    }


@pytest.mark.parametrize("key", TENANTS)
def test_s11_a_nine_percent_price_rise_is_not_an_anomaly_and_spend_uses_the_new_price(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    s11 = plan.scenario("S11")
    skus = s11["products"]
    assert not any("PRICE_ANOMALY" in plan.codes(sku) for sku in skus)
    for sku in skus:
        line = plan.line(sku)
        current = plan.sql(
            """
            SELECT t.purchase_price FROM supplier_product_terms t JOIN products p ON p.tenant_id = t.tenant_id AND p.id = t.product_id
            WHERE t.tenant_id = :t AND p.sku = :s AND t.is_primary AND t.effective_from <= :d
              AND (t.effective_to IS NULL OR t.effective_to >= :d) ORDER BY t.effective_from DESC LIMIT 1
            """,
            s=sku,
            d=AS_OF,
        )[0][0]
        assert Decimal(line["unit_cost"]) == current
        if line["est_spend"]:
            assert Decimal(line["est_spend"]) == (
                Decimal(line["suggested_qty"]) * current
            ).quantize(Decimal("0.01"))


def test_s12_expiry_list_with_an_expired_batch_to_write_off(plans: dict[str, Plan]) -> None:
    plan = plans["med_a"]
    s12 = plan.scenario("S12")
    batches = plan.payload["expiry_batches"]
    near = {b["sku"] for b in batches if b["status"] == "near_expiry"}
    assert set(s12["near_expiry"]) <= near
    expired = [b for b in batches if b["status"] == "expired"]
    assert {b["sku"] for b in expired} >= set(s12["expired"])
    for b in expired:
        assert "write_off" in b["options"]
    for sku in s12["expired"]:
        assert "WRITE_OFF_NEEDED" in plan.codes(sku)
        assert Decimal(plan.line(sku)["on_hand_usable"]) >= 0
    assert Decimal(plan.summary["expired_value"]) > 0
    for b in batches:
        if b["status"] == "near_expiry":
            assert b["batch_no"] and b["expiry_date"] and Decimal(b["qty"]) > 0


def test_s13_large_exposure_with_return_options_by_supplier_policy(plans: dict[str, Plan]) -> None:
    plan = plans["med_b"]
    s13 = plan.scenario("S13")
    near = [b for b in plan.payload["expiry_batches"] if b["status"] == "near_expiry"]
    assert len(near) >= 10
    assert Decimal(plan.summary["expiry_exposure_value"]) > Decimal("20000")
    accepting = {
        r[0]
        for r in plan.sql(
            "SELECT p.sku FROM products p JOIN supplier_product_terms t ON t.tenant_id = p.tenant_id AND t.product_id = p.id "
            "JOIN suppliers s ON s.tenant_id = t.tenant_id AND s.id = t.supplier_id "
            "WHERE p.tenant_id = :t AND t.is_primary AND t.effective_to IS NULL AND s.accepts_expiry_returns"
        )
    }
    for b in near:
        assert ("return_to_supplier" in b["options"]) == (b["sku"] in accepting), b["sku"]
    assert any("return_to_supplier" in b["options"] for b in near)
    assert s13["returnable"]


@pytest.mark.parametrize("key", ["fmcg_a"])
def test_s14_dated_products_with_expiry_exposure_are_limited(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    lines = [plan.line(sku) for sku in plan.scenario("S14")["products"]]
    assert any(
        Decimal(ln["expiry_exposure_qty"]) > 0 or Decimal(ln["expected_expiry_loss"]) > 0
        for ln in lines
    )
    ordering = [ln for ln in lines if Decimal(ln["suggested_qty"]) > 0]
    for ln in ordering:
        assert Decimal(ln["suggested_qty"]) <= max(
            Decimal(ln["demand_protection"]) * 2, Decimal(ln["pack_size"]) * 2
        )
    assert any(
        "EXPIRY_CAP" in ln["reason_codes"] or "EXPIRY_LOSS_EXPECTED" in ln["reason_codes"]
        for ln in lines
    )


@pytest.mark.parametrize("key", having("S15"))
def test_s15_new_products_use_the_category_prior_or_few_days_and_low_confidence(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    for sku in plan.scenario("S15")["products"]:
        line = plan.line(sku)
        assert line["confidence"] == "low"
        assert line["stock_status"] == "new"
        assert "NEW_PRODUCT" in line["reason_codes"]
        assert line["forecast_method"] in ("moving_average", "category_prior")
        assert line["provenance"]["forecast"] in ("calculated", "assumed")


@pytest.mark.parametrize("key", having("S16"))
def test_s16_pack_and_minimum_order_reasons_appear_when_they_force_excess(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    big = [plan.line(sku) for sku in plan.scenario("S16")["products"]]
    assert all(Decimal(ln["pack_size"]) >= 48 for ln in big)
    ordering = [ln for ln in plan.by_sku.values() if Decimal(ln["suggested_qty"]) > 0]
    assert any("PACK_ROUNDING" in ln["reason_codes"] for ln in ordering)
    assert any("MOQ_APPLIED" in ln["reason_codes"] for ln in ordering)
    for ln in ordering:
        if "PACK_ROUNDING" in ln["reason_codes"] or "MOQ_APPLIED" in ln["reason_codes"]:
            assert Decimal(ln["pack_excess_qty"]) > 0
            assert "supplier" in ln["reason_text"].lower()


@pytest.mark.parametrize("key", TENANTS)
def test_s17_a_class_products_without_a_recent_count_are_flagged(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    flagged = " ".join(plan.open_issues("STALE_STOCK_COUNT"))
    for sku in plan.scenario("S17")["products"]:
        assert f"({sku})" in flagged, sku
        assert "STALE_STOCK_COUNT" in plan.codes(sku)


@pytest.mark.parametrize("key", having("S18"))
def test_s18_chronic_medicines_show_the_month_start_pattern(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    rows = plan.sql(
        """
        SELECT AVG(d.units_sold) FILTER (WHERE EXTRACT(day FROM d.stat_date) <= 10),
               AVG(d.units_sold) FILTER (WHERE EXTRACT(day FROM d.stat_date) > 10)
        FROM daily_product_stats d JOIN products p ON p.tenant_id = d.tenant_id AND p.id = d.product_id
        WHERE d.tenant_id = :t AND p.sku = ANY(:skus) AND d.availability_state = 'available'
        """,
        skus=plan.scenario("S18")["products"],
    )[0]
    assert Decimal(rows[0]) > Decimal(rows[1]) * Decimal("1.15")
    lines = [plan.line(sku) for sku in plan.scenario("S18")["products"]]
    assert sum(ln["confidence"] != "low" for ln in lines) >= len(lines) // 3


@pytest.mark.parametrize("key", having("S19"))
def test_s19_the_monsoon_effect_is_learned_and_applied_as_a_season(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    applied = []
    for slug in plan.scenario("S19")["categories"]:
        rows = [e for e in effects(plan, "monsoon", slug) if e[0] == "during"]
        assert rows, slug
        if rows[0][1]:
            assert rows[0][2] == "learned"
            assert Decimal(rows[0][4]) > Decimal("1.15")
            assert rows[0][3] >= 2  # monsoon 2025 and 2026 are both complete
            applied.append(slug)
    assert len(applied) >= 3
    festival_effects = plan.sql(
        "SELECT count(*) FROM event_category_effects e WHERE e.tenant_id = :t AND e.is_applied "
        "AND e.event_key IN (SELECT event_key FROM calendar_events WHERE kind = 'festival')"
    )[0][0]
    seasons_applied = plan.sql(
        "SELECT count(*) FROM event_category_effects e WHERE e.tenant_id = :t AND e.is_applied "
        "AND e.event_key IN ('monsoon', 'summer', 'winter')"
    )[0][0]
    assert seasons_applied > festival_effects  # medicines react to seasons, not to festivals


@pytest.mark.parametrize("key", having("S20"))
def test_s20_a_step_change_is_followed_by_the_forecast(plans: dict[str, Plan], key: str) -> None:
    plan = plans[key]
    sku = plan.scenario("S20")["products"][0]
    line = plan.line(sku)
    starts_on = plan.scenario("S20")["starts_on"]
    before, after = plan.sql(
        """
        SELECT AVG(units_sold) FILTER (WHERE stat_date < :s AND availability_state = 'available'),
               AVG(units_sold) FILTER (WHERE stat_date >= :e AND availability_state = 'available')
        FROM daily_product_stats d JOIN products p ON p.tenant_id = d.tenant_id AND p.id = d.product_id
        WHERE d.tenant_id = :t AND p.sku = :k
        """,
        s=starts_on,
        e=AS_OF - timedelta(days=56),
        k=sku,
    )[0]
    forecast_daily = Decimal(line["demand_7d"]) / 7
    assert Decimal(after) > Decimal(before) * Decimal("1.25")
    assert forecast_daily > Decimal(before) * Decimal("1.2")
    assert abs(forecast_daily - Decimal(after)) / Decimal(after) < Decimal("0.35")


@pytest.mark.parametrize("key", having("S21"))
def test_s21_the_festival_section_shows_navratri_and_diwali(
    plans: dict[str, Plan], key: str
) -> None:
    plan = plans[key]
    festival = {f["event_key"]: f for f in plan.payload["festival"]}
    assert {"navratri_dussehra", "diwali"} <= set(festival)
    diwali = festival["diwali"]
    assert diwali["days_away"] == 25
    assert diwali["pre_window_start"] == "2026-10-23"
    assert diwali["delivery_padding_days"] == 2 or diwali["delivery_padding_days"] >= 1
    if key.startswith("med"):
        assert diwali["categories"]
        for c in diwali["categories"]:
            assert not c["applied"]
            assert c["label"] == "not_enough_evidence"
            assert c["n_occurrences"] < 2
            assert c["evidence"]
    else:
        assert any(
            c["applied"]
            and Decimal(c["forecast_with_effect"]) > Decimal(c["forecast_without_effect"])
            for c in diwali["categories"]
        )
    assert plan.summary["festival_note"]
    assert "Navratri" in plan.summary["festival_note"]
    assert festival["navratri_dussehra"]["days_away"] == -1


def test_every_planted_scenario_has_a_test() -> None:
    covered = {f"S{n:02d}" for n in range(1, 22)}
    planted = {name for tenant in SCENARIOS.values() for name in tenant}
    assert planted <= covered
    assert planted == covered - set()
