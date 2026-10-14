"""Every planted scenario exists in the seeded data with its pattern (scale 0.1)."""

from datetime import timedelta
from typing import Any

import pytest
import yaml
from sqlalchemy import text

from seed.accounts import ENGINE_NEED_CALIBRATION
from seed.model import tenant_uuid
from seed.profiles import PROFILES, SCENARIOS_PATH
from tests.seed.conftest import END, START, Seeded

LAST_60 = END - timedelta(days=59)


def sc(seeded: Seeded, key: str, scenario: str) -> dict[str, Any]:
    return seeded.generated[key].plan.scenarios[scenario]


def rows(seeded: Seeded, key: str, sql: str, **params: Any) -> list[Any]:
    with seeded.session() as session:
        return list(session.execute(text(sql), {"t": tenant_uuid(PROFILES[key]), **params}).all())


def sku_ids(seeded: Seeded, key: str, skus: list[str]) -> list[Any]:
    found = rows(
        seeded, key, "SELECT sku, id FROM products WHERE tenant_id = :t AND sku = ANY(:s)", s=skus
    )
    assert len(found) == len(skus), (key, skus)
    return [r[1] for r in found]


def test_scenarios_yaml_matches_the_plan(seeded: Seeded) -> None:
    data = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))
    for key, gen in seeded.generated.items():
        written = data["tenants"][key]
        assert set(written) == set(gen.plan.scenarios)
        for sid, item in gen.plan.scenarios.items():
            assert written[sid]["expect"] == item["expect"], (key, sid)
            assert written[sid]["summary"] == item["summary"], (key, sid)


@pytest.mark.parametrize("key", list(PROFILES))
def test_every_tenant_lists_its_scenarios(seeded: Seeded, key: str) -> None:
    ids = set(seeded.generated[key].plan.scenarios)
    common = {"S02", "S03", "S05", "S06", "S07", "S10", "S11", "S15", "S16", "S17", "S20", "S21"}
    assert common <= ids
    if key.startswith("fmcg"):
        assert {"S01", "S14"} <= ids
    if key == "fmcg_a":
        assert "S08" in ids
    if key in {"fmcg_b", "med_a", "med_b"}:
        assert "S09" in ids
    if key in {"fmcg_b", "med_b"}:
        assert "S04" in ids
    if key == "med_a":
        assert {"S12", "S18", "S19"} <= ids
    if key == "med_b":
        assert {"S13", "S18", "S19"} <= ids


@pytest.mark.parametrize("key", list(PROFILES))
def test_s05_non_moving_products_have_stock_and_no_recent_sales(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S05")["products"]):
        sold = rows(
            seeded,
            key,
            "SELECT COUNT(*) FROM sale_lines WHERE tenant_id=:t AND product_id=:p AND business_date >= :d",
            p=pid,
            d=LAST_60,
        )[0][0]
        stock = rows(
            seeded,
            key,
            "SELECT COALESCE(SUM(on_hand),0) FROM stock_balances WHERE tenant_id=:t AND product_id=:p",
            p=pid,
        )[0][0]
        assert sold == 0
        assert stock > 0
        before = rows(
            seeded,
            key,
            "SELECT COUNT(*) FROM sale_lines WHERE tenant_id=:t AND product_id=:p AND business_date < :d",
            p=pid,
            d=LAST_60 - timedelta(days=60),
        )[0][0]
        assert before > 0


@pytest.mark.parametrize("key", list(PROFILES))
def test_s06_out_of_stock_products_look_dead_but_were_unavailable(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S06")["products"]):
        stats = rows(
            seeded,
            key,
            "SELECT COUNT(*) FILTER (WHERE availability_state='stocked_out_all_day'), COUNT(*), COALESCE(SUM(units_sold),0) "
            "FROM daily_product_stats WHERE tenant_id=:t AND product_id=:p AND stat_date >= :d",
            p=pid,
            d=LAST_60,
        )[0]
        assert stats[2] == 0
        assert stats[0] / stats[1] >= 0.8
        recorded = rows(
            seeded,
            key,
            "SELECT COUNT(*) FROM stockout_intervals WHERE tenant_id=:t AND product_id=:p AND source='recorded'",
            p=pid,
        )[0][0]
        assert recorded == 0


@pytest.mark.parametrize("key", list(PROFILES))
def test_s03_recorded_and_unrecorded_stockouts(seeded: Seeded, key: str) -> None:
    item = sc(seeded, key, "S03")
    for pid in sku_ids(seeded, key, item["recorded"]):
        assert (
            rows(
                seeded,
                key,
                "SELECT COUNT(*) FROM stockout_intervals WHERE tenant_id=:t AND product_id=:p AND source='recorded'",
                p=pid,
            )[0][0]
            >= 1
        )
    for pid in sku_ids(seeded, key, item["unrecorded"]):
        assert (
            rows(
                seeded,
                key,
                "SELECT COUNT(*) FROM stockout_intervals WHERE tenant_id=:t AND product_id=:p AND source='recorded'",
                p=pid,
            )[0][0]
            == 0
        )
        out_days = rows(
            seeded,
            key,
            "SELECT COUNT(*) FROM daily_product_stats WHERE tenant_id=:t AND product_id=:p AND availability_state='stocked_out_all_day'",
            p=pid,
        )[0][0]
        assert out_days >= 2


@pytest.mark.parametrize("key", list(PROFILES))
def test_s07_an_order_is_overdue_by_at_least_six_days(seeded: Seeded, key: str) -> None:
    cutoff = END + timedelta(days=1) - timedelta(days=6)
    late = rows(
        seeded,
        key,
        "SELECT COUNT(*) FROM purchase_orders WHERE tenant_id=:t AND status IN ('sent','partially_received') AND expected_date <= :d",
        d=cutoff,
    )[0][0]
    assert late >= 1


@pytest.mark.parametrize("key", list(PROFILES))
def test_s10_missing_lead_time_cost_and_expiry(seeded: Seeded, key: str) -> None:
    item = sc(seeded, key, "S10")
    for pid in sku_ids(seeded, key, item["missing_lead_time"]):
        found = rows(
            seeded,
            key,
            "SELECT t.lead_time_days, s.default_lead_time_days FROM supplier_product_terms t "
            "JOIN suppliers s ON s.tenant_id=t.tenant_id AND s.id=t.supplier_id "
            "WHERE t.tenant_id=:t AND t.product_id=:p AND t.effective_to IS NULL",
            p=pid,
        )
        assert found
        assert found[0][0] is None
        assert found[0][1] is None
    for pid in sku_ids(seeded, key, item["missing_cost"]):
        assert (
            rows(
                seeded,
                key,
                "SELECT COUNT(*) FROM supplier_product_terms WHERE tenant_id=:t AND product_id=:p",
                p=pid,
            )[0][0]
            == 0
        )
        assert (
            rows(
                seeded,
                key,
                "SELECT COUNT(*) FROM receipt_lines WHERE tenant_id=:t AND product_id=:p",
                p=pid,
            )[0][0]
            >= 1
        )
    for pid in sku_ids(seeded, key, item["missing_expiry"]):
        tracked = rows(
            seeded, key, "SELECT is_batch_tracked FROM products WHERE tenant_id=:t AND id=:p", p=pid
        )[0][0]
        unbatched = rows(
            seeded,
            key,
            "SELECT COALESCE(SUM(on_hand),0) FROM stock_balances WHERE tenant_id=:t AND product_id=:p AND batch_id IS NULL",
            p=pid,
        )[0][0]
        batches = rows(
            seeded,
            key,
            "SELECT COUNT(*) FROM product_batches WHERE tenant_id=:t AND product_id=:p",
            p=pid,
        )[0][0]
        assert tracked is True
        assert batches == 0
        assert unbatched >= 0


@pytest.mark.parametrize("key", list(PROFILES))
def test_s11_supplier_price_rises_nine_percent(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S11")["products"]):
        found = rows(
            seeded,
            key,
            "SELECT purchase_price, effective_from FROM supplier_product_terms WHERE tenant_id=:t AND product_id=:p ORDER BY effective_from",
            p=pid,
        )
        prices = {str(r[1]): float(r[0]) for r in found}
        assert "2026-01-12" in prices
        earlier = [float(r[0]) for r in found if str(r[1]) < "2026-01-12"][-1]
        assert prices["2026-01-12"] / earlier == pytest.approx(1.09, abs=0.01)


def test_s12_near_expiry_batches_and_one_expired_with_stock(seeded: Seeded) -> None:
    item = sc(seeded, "med_a", "S12")
    for pid in sku_ids(seeded, "med_a", item["near_expiry"]):
        found = rows(
            seeded,
            "med_a",
            "SELECT COUNT(*) FROM v_batch_stock WHERE tenant_id=:t AND product_id=:p AND on_hand > 0 AND expiry_date > :end AND expiry_date <= :end + 90",
            p=pid,
            end=END,
        )[0][0]
        assert found >= 1
    pid = sku_ids(seeded, "med_a", item["expired"])[0]
    assert (
        rows(
            seeded,
            "med_a",
            "SELECT COUNT(*) FROM v_batch_stock WHERE tenant_id=:t AND product_id=:p AND on_hand > 0 AND expiry_date <= :end",
            p=pid,
            end=END,
        )[0][0]
        >= 1
    )


def test_s13_many_near_expiry_batches_some_returnable(seeded: Seeded) -> None:
    item = sc(seeded, "med_b", "S13")
    near = rows(
        seeded,
        "med_b",
        "SELECT COUNT(DISTINCT product_id) FROM v_batch_stock WHERE tenant_id=:t AND on_hand > 0 AND expiry_date > :end AND expiry_date <= :end + 90",
        end=END,
    )[0][0]
    assert near >= 10
    returnable = sku_ids(seeded, "med_b", item["returnable"])
    ok = rows(
        seeded,
        "med_b",
        "SELECT COUNT(*) FROM products p JOIN supplier_product_terms t ON t.tenant_id=p.tenant_id AND t.product_id=p.id AND t.effective_to IS NULL "
        "JOIN suppliers s ON s.tenant_id=t.tenant_id AND s.id=t.supplier_id WHERE p.tenant_id=:t AND p.id = ANY(:ids) AND s.accepts_expiry_returns",
        ids=returnable,
    )[0][0]
    assert ok == 3


@pytest.mark.parametrize("key", ["fmcg_a", "fmcg_b"])
def test_s14_dated_products_have_expiry_exposure(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S14")["products"]):
        found = rows(
            seeded,
            key,
            "SELECT COUNT(*) FROM v_batch_stock WHERE tenant_id=:t AND product_id=:p AND on_hand > 0 AND expiry_date <= :end + 60",
            p=pid,
            end=END,
        )[0][0]
        assert found >= 1


@pytest.mark.parametrize("key", list(PROFILES))
def test_s15_new_products_launched_five_weeks_before_the_end(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S15")["products"]):
        launched = rows(
            seeded, key, "SELECT launched_on FROM products WHERE tenant_id=:t AND id=:p", p=pid
        )[0][0]
        assert launched == END - timedelta(days=34)
        first = rows(
            seeded,
            key,
            "SELECT MIN(business_date) FROM sale_lines WHERE tenant_id=:t AND product_id=:p",
            p=pid,
        )[0][0]
        assert first is None or first >= launched


@pytest.mark.parametrize("key", list(PROFILES))
def test_s16_pack_and_minimum_order_force_excess(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S16")["products"]):
        pack, moq = rows(
            seeded,
            key,
            "SELECT pack_size, moq_units FROM supplier_product_terms WHERE tenant_id=:t AND product_id=:p AND effective_to IS NULL",
            p=pid,
        )[0]
        assert pack >= 48
        assert moq >= 2 * pack


@pytest.mark.parametrize("key", list(PROFILES))
def test_s17_a_class_products_have_no_recent_count(seeded: Seeded, key: str) -> None:
    for pid in sku_ids(seeded, key, sc(seeded, key, "S17")["products"]):
        last = rows(
            seeded,
            key,
            "SELECT MAX(c.count_date) FROM stock_count_lines l JOIN stock_counts c ON c.tenant_id=l.tenant_id AND c.id=l.count_id "
            "WHERE l.tenant_id=:t AND l.product_id=:p",
            p=pid,
        )[0][0]
        assert last is None or (END - last).days > 45


def _planted(seeded: Seeded, key: str, start: str, end: str, slug: str) -> float:
    """Average event multiplier recorded with the true demand: what the generator planted."""
    from datetime import date

    sql = (
        "SELECT AVG(d.event_multiplier) FROM synthetic_true_demand d "
        "JOIN products p ON p.tenant_id=d.tenant_id AND p.id=d.product_id "
        "JOIN categories c ON c.tenant_id=p.tenant_id AND c.id=p.category_id "
        "WHERE d.tenant_id=:t AND c.slug=:slug AND d.stat_date BETWEEN :a AND :b"
    )
    return float(
        rows(seeded, key, sql, slug=slug, a=date.fromisoformat(start), b=date.fromisoformat(end))[
            0
        ][0]
    )


@pytest.mark.parametrize("key", ["fmcg_a", "fmcg_b"])
def test_s01_diwali_uplift_in_festival_categories(seeded: Seeded, key: str) -> None:
    assert _planted(seeded, key, "2025-10-18", "2025-10-23", "dry-fruits") > 1.8
    assert _planted(seeded, key, "2025-10-18", "2025-10-23", "festival-puja") > 2.2
    assert _planted(seeded, key, "2025-10-18", "2025-10-23", "chocolates-sweets") > 1.6
    assert _planted(seeded, key, "2025-10-18", "2025-10-23", "beverages") == pytest.approx(
        1.0, abs=0.05
    )


@pytest.mark.parametrize("key", ["fmcg_a", "fmcg_b"])
def test_s02_negative_case_has_no_real_effect(seeded: Seeded, key: str) -> None:
    plan = seeded.generated[key].plan
    for event, slug in plan.no_effect_pairs:
        assert event in {"holi", "raksha_bandhan", "christmas_ny"}
        window = {
            "holi": ("2026-03-03", "2026-03-04"),
            "raksha_bandhan": ("2025-08-09", "2025-08-09"),
            "christmas_ny": ("2025-12-24", "2026-01-01"),
        }[event]
        assert _planted(seeded, key, window[0], window[1], slug) == pytest.approx(1.0, abs=0.001)
    boosted = _planted(seeded, key, "2026-03-03", "2026-03-04", "chocolates-sweets")
    assert boosted > 1.2


@pytest.mark.parametrize("key", ["med_a", "med_b"])
def test_s02_medical_single_occurrence_has_a_chance_uplift(seeded: Seeded, key: str) -> None:
    item = sc(seeded, key, "S02")
    assert _planted(seeded, key, "2025-10-18", "2025-10-23", item["category"]) > 1.2
    other = "analgesics-antipyretics"
    assert _planted(seeded, key, "2025-10-18", "2025-10-23", other) == pytest.approx(1.0, abs=0.001)
    inside = rows(
        seeded,
        key,
        "SELECT COUNT(*) FROM calendar_events WHERE event_key='diwali' AND start_date >= :a AND end_date <= :b",
        a=START,
        b=END,
    )[0][0]
    assert inside == 1


@pytest.mark.parametrize("key", ["med_a", "med_b"])
def test_s18_chronic_medicines_refill_at_month_start(seeded: Seeded, key: str) -> None:
    ids = sku_ids(seeded, key, sc(seeded, key, "S18")["products"])
    sql = (
        "SELECT AVG(true_demand) FILTER (WHERE EXTRACT(DAY FROM stat_date) <= 10), "
        "AVG(true_demand) FILTER (WHERE EXTRACT(DAY FROM stat_date) > 10) "
        "FROM synthetic_true_demand WHERE tenant_id=:t AND product_id = ANY(:ids)"
    )
    early, late = rows(seeded, key, sql, ids=ids)[0]
    assert float(early) / float(late) > 1.3


@pytest.mark.parametrize("key", ["med_a", "med_b"])
def test_s19_monsoon_lifts_illness_categories(seeded: Seeded, key: str) -> None:
    sql = (
        "SELECT AVG(d.true_demand) FILTER (WHERE d.stat_date BETWEEN DATE '2025-07-01' AND DATE '2025-09-15'), "
        "AVG(d.true_demand) FILTER (WHERE d.stat_date BETWEEN DATE '2025-12-01' AND DATE '2026-02-10') "
        "FROM synthetic_true_demand d JOIN products p ON p.tenant_id=d.tenant_id AND p.id=d.product_id "
        "JOIN categories c ON c.tenant_id=p.tenant_id AND c.id=p.category_id WHERE d.tenant_id=:t AND c.slug = ANY(:slugs)"
    )
    monsoon, winter = rows(seeded, key, sql, slugs=["gastro-antacids", "dermatology"])[0]
    assert float(monsoon) / float(winter) > 1.05


@pytest.mark.parametrize("key", list(PROFILES))
def test_s20_a_product_steps_up_by_half(seeded: Seeded, key: str) -> None:
    item = sc(seeded, key, "S20")
    pid = sku_ids(seeded, key, item["products"])[0]
    start = seeded.generated[key].plan.start
    day = start + timedelta(days=545 - 190)
    sql = (
        "SELECT AVG(true_demand) FILTER (WHERE stat_date < :d), AVG(true_demand) FILTER (WHERE stat_date >= :d) "
        "FROM synthetic_true_demand WHERE tenant_id=:t AND product_id=:p"
    )
    before, after = rows(seeded, key, sql, p=pid, d=day)[0]
    assert float(after) / float(before) > 1.15


def test_s21_upcoming_festival_windows_are_in_the_calendar(seeded: Seeded) -> None:
    found = rows(
        seeded,
        "fmcg_a",
        "SELECT slug, start_date FROM calendar_events WHERE slug IN ('navratri_dussehra-2026','diwali-2026') ORDER BY slug",
    )
    assert [str(r[1]) for r in found] == ["2026-11-06", "2026-10-11"]


def test_budgets_follow_the_scenario(seeded: Seeded) -> None:
    budgets = {}
    for key in PROFILES:
        value = rows(seeded, key, "SELECT weekly_budget FROM business_settings WHERE tenant_id=:t")[
            0
        ][0]
        assert value is not None
        assert value > 0
        budgets[key] = float(value)
    for key, gen in seeded.generated.items():
        cogs = gen.data.weekly_cogs[-8:]
        need = sum(cogs) / len(cogs) * 1.10 * ENGINE_NEED_CALIBRATION[key]
        assert budgets[key] / need == pytest.approx(gen.plan.budget_factor, abs=0.15)
