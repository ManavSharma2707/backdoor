"""Report, decision, insight and job endpoints on the seeded database, with two tenants."""

from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from app.models.purchasing import PurchaseOrder
from tests.pipeline.conftest import API, JOB_TOKEN, Api

# --------------------------------------------------------------------------- reading


def test_list_latest_and_get(api: Api) -> None:
    listing = api.get("/reports").json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert (item["week_start"], item["version"], item["is_current"], item["status"]) == (
        "2026-10-12",
        1,
        True,
        "ready",
    )
    assert item["profile"] == "light"
    latest = api.get("/reports/latest").json()
    assert latest["id"] == api.report_a
    full = api.get(f"/reports/{api.report_a}").json()
    assert "lines" not in full["payload"]
    assert full["summary"] == full["payload"]["summary"]
    assert full["payload"]["tenant"]["name"].startswith("Shree Sai")
    totals = full["decision_totals"]
    assert (totals["approved"], totals["edited"], totals["rejected"]) == (0, 0, 0)
    assert totals["pending"] >= 1
    assert totals["approved_spend"] == "0.00"
    assert totals["budget"] == totals["budget_remaining"] == full["summary"]["budget"]
    assert totals["over_budget"] is False
    assert full["notes_count"] == 0


def test_a_business_cannot_see_another_businesses_plan(api: Api) -> None:
    line = api.lines()[0]["id"]
    for method, path in (
        ("get", f"/reports/{api.report_a}"),
        ("get", f"/reports/{api.report_a}/lines"),
        ("get", f"/reports/{api.report_a}/lines/{line}"),
        ("get", f"/reports/{api.report_a}/notes"),
    ):
        response = getattr(api, method)(path, headers=api.b)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "NOT_FOUND"
    assert (
        api.put(f"/report-lines/{line}/decision", {"decision": "rejected"}, api.b).status_code
        == 404
    )
    assert api.post(f"/reports/{api.report_a}/notes", {"body": "x"}, api.b).status_code == 404
    assert (
        api.post(
            f"/reports/{api.report_a}/decisions/bulk",
            {"line_ids": [line], "decision": "rejected"},
            api.b,
        ).status_code
        == 404
    )
    assert api.post(f"/reports/{api.report_a}/scenario", {}, api.b).status_code == 404
    assert api.post(f"/reports/{api.report_a}/purchase-orders", None, api.b).status_code == 404
    other = api.get("/reports", api.b).json()
    assert [i["id"] for i in other["items"]] == [api.report_b]


def test_lines_filters_sorting_and_paging(api: Api) -> None:
    summary = api.get(f"/reports/{api.report_a}").json()["summary"]
    everything = api.lines()
    assert len(everything) == 92
    buy = api.lines(section="buy")
    assert len(buy) == summary["lines_buy"]
    assert all("buy" in ln["sections"] for ln in buy)
    assert len(api.lines(section="watch")) == summary["lines_watch"]
    critical = api.lines(risk="critical")
    assert len(critical) == summary["critical_count"]
    assert {ln["risk_level"] for ln in critical} == {"critical"}
    supplier = buy[0]["supplier_id"]
    assert {ln["supplier_id"] for ln in api.lines(supplier_id=supplier)} == {supplier}
    category = everything[0]["category_id"]
    assert {ln["category_id"] for ln in api.lines(category_id=category)} == {category}
    found = api.lines(q="ghee")
    assert found
    assert all("ghee" in (ln["name"] + ln["sku"]).lower() for ln in found)
    by_spend = api.lines(section="buy", sort="spend:desc")
    spends = [Decimal(ln["est_spend"] or "0") for ln in by_spend]
    assert spends == sorted(spends, reverse=True)
    page = api.get(f"/reports/{api.report_a}/lines", params={"page": 2, "page_size": 10}).json()
    assert (page["page"], page["page_size"], page["total"], len(page["items"])) == (2, 10, 92, 10)
    assert api.get(f"/reports/{api.report_a}/lines", params={"sort": "bogus"}).status_code == 422
    assert api.get(f"/reports/{api.report_a}/lines", params={"risk": "scary"}).status_code == 422
    line = everything[0]
    for key in ("sku", "reason_text", "suggested_qty", "allocated_qty", "provenance", "warnings"):
        assert key in line
    assert all(
        isinstance(ln[k], str) for ln in everything for k in ("suggested_qty", "on_hand_usable")
    )


def test_line_detail_has_history_and_the_forecast_series(api: Api) -> None:
    line = api.lines(section="buy")[0]
    detail = api.get(f"/reports/{api.report_a}/lines/{line['id']}").json()
    assert detail["id"] == line["id"]
    assert len(detail["forecast"]) == 28
    assert detail["forecast"][0]["date"] == "2026-10-12"
    assert len(detail["history"]) == 56
    assert detail["decisions"] == []
    assert detail["payload"]["reason_text"] == line["reason_text"]
    assert (
        api.get(f"/reports/{api.report_a}/lines/00000000-0000-0000-0000-000000000000").status_code
        == 404
    )


# --------------------------------------------------------------------------- deciding


def funded(api: Api) -> list[dict[str, Any]]:
    return [
        ln
        for ln in api.lines(section="buy")
        if Decimal(ln["allocated_qty"]) > 0 and ln["unit_cost"]
    ]


def test_approve_edit_reject_and_totals(api: Api) -> None:
    a, b, c = funded(api)[:3]
    ok = api.put(f"/report-lines/{a['id']}/decision", {"decision": "approved"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["decision"]["final_qty"] == a["allocated_qty"]
    assert body["totals"]["approved"] == 1
    assert Decimal(body["totals"]["approved_spend"]) == Decimal(a["funded_spend"])
    pack = Decimal(b["pack_size"])
    edit = api.put(
        f"/report-lines/{b['id']}/decision",
        {"decision": "edited", "final_qty": str(pack), "reason_code": "shelf_space"},
    ).json()
    assert edit["totals"]["edited"] == 1
    assert Decimal(edit["totals"]["approved_spend"]) == Decimal(a["funded_spend"]) + (
        pack * Decimal(b["unit_cost"])
    ).quantize(Decimal("0.01"))
    reject = api.put(
        f"/report-lines/{c['id']}/decision", {"decision": "rejected", "reason_code": "cash_tight"}
    ).json()
    assert reject["totals"]["rejected"] == 1
    assert reject["decision"]["final_qty"] == "0.000"
    listed = {ln["id"]: ln for ln in api.lines(decision="approved")}
    assert listed[a["id"]]["decision"]["decision"] == "approved"
    assert {ln["id"] for ln in api.lines(decision="rejected")} == {c["id"]}
    pending = api.get(f"/reports/{api.report_a}").json()["decision_totals"]["pending"]
    assert pending == len(funded(api)) - 3


def audit_count(api: Api, line_id: str) -> int:
    with api.db.session() as s:
        return int(
            s.scalar(
                text(
                    "SELECT count(*) FROM audit_logs "
                    "WHERE action LIKE 'decision.%' AND entity_id = :l"
                ),
                {"l": line_id},
            )
            or 0
        )


def test_a_new_decision_replaces_the_live_one_and_keeps_the_history(api: Api) -> None:
    line = funded(api)[0]
    audited_before = audit_count(api, line["id"])
    api.put(f"/report-lines/{line['id']}/decision", {"decision": "approved"})
    api.put(f"/report-lines/{line['id']}/decision", {"decision": "rejected"})
    detail = api.get(f"/reports/{api.report_a}/lines/{line['id']}").json()
    assert [d["decision"] for d in detail["decisions"]] == ["rejected", "approved"]
    live = api.get(f"/reports/{api.report_a}/lines/{line['id']}").json()["decision"]
    assert live["decision"] == "rejected"
    with api.db.session() as s:
        live_rows = s.scalar(
            text(
                "SELECT count(*) FROM recommendation_decisions WHERE line_id = :l AND superseded_at IS NULL"
            ),
            {"l": line["id"]},
        )
        assert live_rows == 1
    assert audit_count(api, line["id"]) - audited_before == 2


def test_edits_must_use_whole_packs_unless_the_reason_is_other(api: Api) -> None:
    line = next(ln for ln in funded(api) if Decimal(ln["pack_size"]) > 1)
    url = f"/report-lines/{line['id']}/decision"
    pack = Decimal(line["pack_size"])
    off = str(pack + 1)
    refused = api.put(url, {"decision": "edited", "final_qty": off})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["field"] == "final_qty"
    assert (
        api.put(url, {"decision": "edited", "final_qty": off, "reason_code": "other"}).status_code
        == 422
    )
    allowed = api.put(
        url,
        {
            "decision": "edited",
            "final_qty": off,
            "reason_code": "other",
            "reason_text": "Supplier offered a loose carton",
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["off_pack"] is True
    assert api.put(url, {"decision": "edited"}).status_code == 422
    assert api.put(url, {"decision": "edited", "final_qty": "0"}).status_code == 422
    assert api.put(url, {"decision": "approved", "reason_code": "made_up"}).status_code == 422
    assert api.put(url, {"decision": "edited", "final_qty": 5}).status_code == 422  # floats refused


def test_an_unfunded_line_cannot_be_approved_as_it_is(api: Api) -> None:
    line = next(
        ln
        for ln in api.lines()
        if Decimal(ln["allocated_qty"]) == 0 and Decimal(ln["suggested_qty"]) > 0
    )
    response = api.put(f"/report-lines/{line['id']}/decision", {"decision": "approved"})
    assert response.status_code == 409
    assert "Nothing is funded" in response.json()["error"]["message"]


def test_bulk_decisions_report_what_they_skipped(api: Api) -> None:
    funded_ids = [ln["id"] for ln in funded(api)[:4]]
    unfunded = next(
        ln["id"]
        for ln in api.lines()
        if Decimal(ln["allocated_qty"]) == 0 and Decimal(ln["suggested_qty"]) > 0
    )
    body = api.post(
        f"/reports/{api.report_a}/decisions/bulk",
        {"line_ids": [*funded_ids, unfunded], "decision": "approved"},
    ).json()
    assert body["applied"] == 4
    assert [s["line_id"] for s in body["skipped"]] == [unfunded]
    assert body["totals"]["approved"] == 4
    rejected = api.post(
        f"/reports/{api.report_a}/decisions/bulk",
        {"line_ids": [unfunded], "decision": "rejected", "reason_code": "not_needed"},
    ).json()
    assert rejected["applied"] == 1
    assert (
        api.post(
            f"/reports/{api.report_a}/decisions/bulk",
            {"line_ids": ["00000000-0000-0000-0000-000000000000"], "decision": "approved"},
        ).status_code
        == 404
    )
    assert (
        api.post(
            f"/reports/{api.report_a}/decisions/bulk", {"line_ids": [], "decision": "approved"}
        ).status_code
        == 422
    )


def test_purchase_orders_from_approved_lines_and_blocked_lines(api: Api) -> None:
    all_buy = api.lines(section="buy")
    blocked = next(ln for ln in all_buy if ln["unit_cost"] is None)
    ready = [
        ln
        for ln in all_buy
        if Decimal(ln["allocated_qty"]) > 0 and ln["unit_cost"] and ln["supplier_id"]
    ][:6]
    for ln in ready:
        assert (
            api.put(f"/report-lines/{ln['id']}/decision", {"decision": "approved"}).status_code
            == 200
        )
    assert (
        api.put(
            f"/report-lines/{blocked['id']}/decision",
            {
                "decision": "edited",
                "final_qty": "5",
                "reason_code": "other",
                "reason_text": "Bought over the counter",
            },
        ).status_code
        == 200
    )
    refused = api.post(f"/reports/{api.report_a}/purchase-orders")
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "MISSING_SUPPLIER_OR_COST"
    assert [d["field"] for d in error["details"]] == [f"lines[{blocked['sku']}]"]
    api.put(
        f"/report-lines/{blocked['id']}/decision",
        {"decision": "rejected", "reason_code": "not_needed"},
    )
    created = api.post(
        f"/reports/{api.report_a}/purchase-orders",
        headers={**api.a, "Idempotency-Key": "po-run-0001"},
    )
    assert created.status_code == 201
    result = created.json()
    suppliers = {ln["supplier_id"] for ln in ready}
    assert len(result["purchase_orders"]) == len(suppliers)
    total = sum(Decimal(po["value"]) for po in result["purchase_orders"])
    assert total == sum(Decimal(ln["funded_spend"]) for ln in ready)
    assert all(po["status"] == "draft" for po in result["purchase_orders"])
    lines = [pl for po in result["purchase_orders"] for pl in po["lines"]]
    assert {pl["sku"] for pl in lines} == {ln["sku"] for ln in ready}
    with api.db.session() as s:
        sources = {
            r[0]
            for r in s.execute(
                select(PurchaseOrder.source, PurchaseOrder.recommendation_run_id).where(
                    PurchaseOrder.source == "recommendation"
                )
            )
        }
        assert sources == {"recommendation"}
        linked = s.scalar(
            text(
                "SELECT count(*) FROM purchase_order_lines WHERE recommendation_line_id IS NOT NULL"
            )
        )
        assert linked == len(ready)
    replay = api.post(
        f"/reports/{api.report_a}/purchase-orders",
        headers={**api.a, "Idempotency-Key": "po-run-0001"},
    )
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json() == result
    again = api.post(f"/reports/{api.report_a}/purchase-orders").json()
    assert again["purchase_orders"] == []
    assert len(again["skipped"]) == len(ready)


def test_notes(api: Api) -> None:
    line = api.lines()[0]["id"]
    made = api.post(
        f"/reports/{api.report_a}/notes", {"body": "Ask about the Diwali stock", "line_id": line}
    )
    assert made.status_code == 201
    api.post(f"/reports/{api.report_a}/notes", {"body": "Budget is tight this week"})
    listed = api.get(f"/reports/{api.report_a}/notes").json()
    assert [n["body"] for n in listed] == [
        "Ask about the Diwali stock",
        "Budget is tight this week",
    ]
    assert listed[0]["source"] == "user"
    assert listed[0]["author"]
    assert api.get(f"/reports/{api.report_a}").json()["notes_count"] == 2
    other_line = api.get(f"/reports/{api.report_b}/lines", headers=api.b).json()["items"][0]["id"]
    assert (
        api.post(f"/reports/{api.report_a}/notes", {"body": "x", "line_id": other_line}).status_code
        == 404
    )
    assert api.post(f"/reports/{api.report_a}/notes", {"body": ""}).status_code == 422


# --------------------------------------------------------------------------- scenario


def test_a_scenario_never_writes_plan_rows(api: Api) -> None:
    before = {
        t: api.db.engine.connect().execute(text(f"SELECT count(*) FROM {t}")).scalar()
        for t in (
            "recommendation_runs",
            "recommendation_lines",
            "weekly_reports",
            "forecast_runs",
            "forecast_values",
        )
    }
    base_budget = Decimal(api.get(f"/reports/{api.report_a}").json()["summary"]["budget"])
    body = api.post(
        f"/reports/{api.report_a}/scenario", {"weekly_budget": str(base_budget / 2)}
    ).json()
    assert Decimal(body["scenario"]["planned_spend"]) <= base_budget / 2
    assert Decimal(body["scenario"]["planned_spend"]) < Decimal(body["base"]["planned_spend"])
    assert Decimal(body["scenario"]["unfunded_value"]) > Decimal(body["base"]["unfunded_value"])
    assert body["lines_changed"]
    assert "Nothing was saved" in body["note"]
    unlimited = api.post(f"/reports/{api.report_a}/scenario", {"clear_budget": True}).json()
    assert unlimited["scenario"]["shortfall"] == "0.00"
    assert Decimal(unlimited["scenario"]["planned_spend"]) == Decimal(
        unlimited["scenario"]["needed"]
    )
    after = {
        t: api.db.engine.connect().execute(text(f"SELECT count(*) FROM {t}")).scalar()
        for t in before
    }
    assert after == before


def test_scenario_levers(api: Api) -> None:
    lines = api.lines(section="buy")
    drop = lines[0]
    out = api.post(
        f"/reports/{api.report_a}/scenario", {"excluded_product_ids": [drop["product_id"]]}
    ).json()
    assert any(
        c["base"]["sku"] == drop["sku"] and c["scenario"] is None for c in out["lines_changed"]
    )
    more_demand = api.post(f"/reports/{api.report_a}/scenario", {"demand_multiplier": 1.5}).json()
    assert Decimal(more_demand["scenario"]["needed"]) > Decimal(more_demand["base"]["needed"])
    higher_service = api.post(f"/reports/{api.report_a}/scenario", {"service_level": 0.99}).json()
    assert Decimal(higher_service["scenario"]["needed"]) >= Decimal(
        higher_service["base"]["needed"]
    )
    late = api.post(
        f"/reports/{api.report_a}/scenario", {"supplier_delay_days": {drop["supplier_id"]: 6}}
    ).json()
    assert late["scenario"]["critical_lines"] >= late["base"]["critical_lines"]
    assert api.post(f"/reports/{api.report_a}/scenario", {"service_level": 2}).status_code == 422
    assert api.post(f"/reports/{api.report_a}/scenario", {"nonsense": 1}).status_code == 422


# --------------------------------------------------------------------------- insights


def test_dashboard(api: Api) -> None:
    summary = api.get("/dashboard/summary").json()
    assert summary["plan"]["week_start"] == "2026-10-12"
    kpis = summary["kpis"]
    assert Decimal(kpis["stock_value"]) > 0
    assert kpis["critical_lines"] >= 1
    assert summary["needs_attention"]
    first = summary["needs_attention"][0]
    assert {"line_id", "report_id", "sku", "name", "risk_level", "headline"} <= set(first)
    trends = api.get("/dashboard/trends", params={"weeks": 12}).json()
    assert len(trends["weeks"]) == 12
    assert all(Decimal(w["revenue"]) > 0 for w in trends["weeks"])
    assert any(b["event_key"] == "ganesh_chaturthi" for b in trends["festival_bands"])
    cover = api.get("/dashboard/cover-by-category").json()
    assert len(cover["categories"]) == 17
    assert api.get("/dashboard/trends", params={"weeks": 1}).status_code == 422
    other = api.get("/dashboard/summary", api.b).json()
    assert other["plan"]["id"] == api.report_b


def test_insights(api: Api) -> None:
    movers = api.get("/insights/movers").json()
    assert sum(movers["counts"].values()) == 92
    assert all(movers["counts"][k] > 0 for k in "ABC")
    assert movers["non_moving"] or movers["slow"]
    accuracy = api.get("/insights/forecast-accuracy").json()
    assert accuracy["run"]["profile"] == "light"
    assert accuracy["tenant"]["selected"]["wape"] is not None
    assert accuracy["tenant"]["baseline"]["wape"] is not None
    assert accuracy["segments"]
    seg = accuracy["segments"][0]
    assert {"segment", "selected", "selected_metrics", "baseline_metrics"} <= set(seg)
    narrowed = api.get("/insights/forecast-accuracy", params={"segment": "smooth"}).json()
    assert all("smooth" in s["segment"] for s in narrowed["segments"])
    series = api.get("/insights/forecast-vs-actual", params={"weeks": 8}).json()["series"]
    assert len(series) == 8
    assert all(w["actual"] >= 0 for w in series)
    effects = api.get("/insights/festival-effects").json()["events"]
    diwali = next(e for e in effects if e["event_key"] == "diwali")
    assert diwali["dates_may_shift"] is False
    assert any(c["applied"] for c in diwali["categories"])
    scorecards = api.get("/insights/suppliers").json()
    assert len(scorecards) >= 6
    assert any(s["fill_rate"] for s in scorecards)
    one = api.get(f"/suppliers/{scorecards[0]['supplier_id']}/scorecard").json()
    assert one["supplier_id"] == scorecards[0]["supplier_id"]
    assert api.get(f"/suppliers/{scorecards[0]['supplier_id']}/scorecard", api.b).status_code == 404
    waste = api.get("/insights/expiry-waste", params={"months": 6}).json()
    assert Decimal(waste["total_written_off_value"]) >= 0
    assert waste["by_reason"]


def test_data_quality(api: Api) -> None:
    issues = api.get("/data-quality/issues", params={"page_size": 100}).json()
    codes = {i["code"] for i in issues["items"]}
    assert {"MISSING_COST", "MISSING_SUPPLIER", "PO_OVERDUE"} <= codes
    assert all(i["severity"] in ("error", "warning", "info") for i in issues["items"])
    assert issues["items"][0]["severity"] == "error"
    before = issues["total"]
    run = api.post("/data-quality/run").json()
    assert set(run) == {"inserted", "updated", "resolved"}
    after = api.get("/data-quality/issues").json()["total"]
    assert abs(after - before) < 40
    assert api.get("/data-quality/issues", api.b).json()["items"] != issues["items"]


# --------------------------------------------------------------------------- jobs


def test_generating_a_report(api: Api) -> None:
    refused = api.post("/reports/generate", {"week_start": "2026-10-12"})
    assert refused.status_code == 409
    assert "force" in refused.json()["error"]["message"]
    assert api.post("/reports/generate", {"week_start": "2026-10-13"}).status_code == 422
    assert api.post("/reports/generate", {"week_start": "2030-01-07"}).status_code == 422
    accepted = api.post("/reports/generate", {"week_start": "2026-10-12", "force": True})
    assert accepted.status_code == 202
    job = accepted.json()
    # The background task has run by the time the test client answers.
    run = api.get(f"/jobs/runs/{job['id']}").json()
    assert run["status"] == "succeeded"
    assert run["result"]["version"] == 2
    listing = api.get("/reports").json()["items"]
    assert [(r["version"], r["is_current"]) for r in listing] == [(2, True), (1, False)]
    old = api.lines()  # the old plan id is now stale for decisions
    assert old
    stale = api.put(f"/report-lines/{old[0]['id']}/decision", {"decision": "rejected"})
    assert stale.status_code == 409
    assert "newer version" in stale.json()["error"]["message"]
    jobs = api.get("/jobs/runs").json()
    assert jobs["total"] == 1
    assert api.get(f"/jobs/runs/{job['id']}", api.b).status_code == 404


def test_job_token_endpoint(api: Api) -> None:
    client = api.client
    assert client.post(f"{API}/jobs/monday-report").status_code == 401
    assert (
        client.post(f"{API}/jobs/monday-report", headers={"X-Job-Token": "nope"}).status_code == 401
    )
    assert (
        client.post(
            f"{API}/jobs/monday-report",
            params={"tenant": "ghost"},
            headers={"X-Job-Token": JOB_TOKEN},
        ).status_code
        == 404
    )
    done = client.post(
        f"{API}/jobs/monday-report",
        params={"tenant": "sanjivani-medical"},
        headers={"X-Job-Token": JOB_TOKEN},
    )
    assert done.status_code == 202
    body = done.json()
    assert body["job_run_ids"] == []
    assert "already exists" in body["skipped"][0]
    forced = client.post(
        f"{API}/jobs/monday-report",
        params={"tenant": "sanjivani-medical", "force": "true"},
        headers={"X-Job-Token": JOB_TOKEN},
    )
    job_id = forced.json()["job_run_ids"][0]
    status = client.get(f"{API}/jobs/runs/{job_id}", headers={"X-Job-Token": JOB_TOKEN}).json()
    assert status["status"] == "succeeded"
    assert client.get(f"{API}/jobs/runs/{job_id}", headers=api.a).status_code == 404
    assert client.get(f"{API}/jobs/runs/{job_id}", headers=api.b).status_code == 200
    assert client.get(f"{API}/jobs/runs/{job_id}").status_code == 401
