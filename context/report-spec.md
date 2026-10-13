# Monday report specification

The Monday plan is the product. It must be readable by a shop owner in five minutes and traceable line by line to stored data.

Every value is tagged with where it came from: **Observed** (read from records), **Calculated** (derived by the engine), or **Assumed** (default, estimate or owner-entered setting). The UI shows a small tag, exports show a column or footnote.

---

## 1. Sections

| # | Section | Content |
|---|---|---|
| 1 | Summary | Planned spend, budget, remaining or shortfall, critical lines count, stock not moving value, near-expiry value and count, data warnings count, forecast confidence mix, festival note if one is within 21 days |
| 2 | Buy this week | Lines with a quantity to order. Product, supplier, forecast over days to cover, sellable stock, incoming, buffer stock, raw need, pack and minimum order, suggested, funded quantity, spend, risk, confidence, decision, reason |
| 3 | Do not buy yet | Lines with enough cover. Days of cover, sellable stock, incoming, next review |
| 4 | Watch closely | Lines likely to run out before delivery or with overdue orders. Expected risk date, probability band, what can be done now |
| 5 | Reduce exposure | Slow, non-moving (and "check first" unverified), excess, near-expiry batches with batch id, quantity, expiry, value, operational options |
| 6 | Festival and season | Upcoming events within 35 days, categories affected, forecast with and without the effect, evidence and label (learned, set by you, not enough evidence), delivery delay padding in use |
| 7 | Budget view | Budget, needed, funded, shortfall, unfunded lines ranked, lines still at risk after funding, the priority score explanation |
| 8 | Data and confidence notes | Issues from the DQ checks relevant to this plan, assumptions in use (default lead time, missing counts), censored history notes |
| 9 | Agent review (optional) | Notes written by the Monday Analyst, clearly labelled as notes, never changing numbers |

## 2. Line fields (`recommendation_lines` mapped to display)

| Display label | Field | Tag |
|---|---|---|
| Product, SKU, category | product | Observed |
| Supplier | supplier | Observed |
| Forecast for next 7 days | `demand_7d` | Calculated |
| Forecast for days to cover | `demand_protection` | Calculated |
| Days to cover | `protection_days` (with lead time source) | Calculated, Assumed if lead time defaulted |
| Sellable stock | `on_hand_usable` after expiry loss | Observed, Calculated |
| Expected to expire unsold | `expected_expiry_loss` | Calculated |
| Incoming (confirmed) | `incoming_confirmed` | Observed |
| Incoming ignored (late orders) | `incoming_excluded_overdue` | Observed |
| Stock you can count on | `inventory_position` | Calculated |
| Buffer stock | `safety_stock` | Calculated |
| Raw need | `raw_qty` | Calculated |
| Minimum order, pack of | `moq_units`, `pack_size` | Observed |
| Suggested quantity | `suggested_qty` | Calculated |
| Funded quantity | `allocated_qty` | Calculated |
| Extra from pack rounding | `pack_excess_qty` | Calculated |
| Unit cost, spend | `unit_cost`, `est_spend` | Observed, Calculated |
| Risk | `risk_level`, `projected_stockout_date` | Calculated |
| Forecast confidence | `confidence` with method and error | Calculated |
| Your decision | latest `recommendation_decisions` | Observed |
| Reason | `reason_text` | Calculated |

### Reason text
Generated from `reason_codes` by templates in `engine/report_builder.py` (no LLM). Plain sentences, no dashes, example:
"Demand for the next 10 days is about 30 packs. You have 12 on the shelf and 5 on the way, and we keep 4 as buffer, so you are short by 17. The supplier sells in packs of 10, so we suggest 20."

Reason codes: `SHORT_FOR_COVER`, `FESTIVAL_UPLIFT`, `PROMO_PLANNED`, `PACK_ROUNDING`, `MOQ_APPLIED`, `EXPIRY_CAP`, `EXPIRY_LOSS_EXPECTED`, `OVERDUE_ORDER_IGNORED`, `BUDGET_LIMITED`, `COVERED`, `EXCESS_STOCK`, `SLOW_MOVING`, `NON_MOVING`, `CHECK_BEFORE_DEAD`, `OUT_OF_STOCK_NOW`, `LOW_CONFIDENCE`, `NEW_PRODUCT`, `MISSING_COST`.

## 3. Snapshot JSON (`weekly_reports.payload`)

```jsonc
{
  "schema_version": 1,
  "tenant": {"name": "...", "business_type": "fmcg", "is_synthetic": true},
  "week_start": "2026-10-12",
  "data_cutoff": "2026-10-11T18:30:00Z",
  "model_version": "forecast-engine 1.0.0",
  "profile": "full",
  "settings": { ... snapshot of used settings ... },
  "summary": {
    "planned_spend": "182340.00", "budget": "200000.00", "budget_remaining": "17660.00",
    "shortfall": "0.00", "lines_buy": 41, "lines_watch": 9, "lines_reduce": 12,
    "critical_count": 3, "non_moving_value": "21400.00", "expiry_exposure_value": "6800.00",
    "near_expiry_batches": 7, "dq_errors": 1, "dq_warnings": 5,
    "confidence_mix": {"high": 52, "medium": 30, "low": 10}
  },
  "festival": [{ "event_key": "diwali", "name": "Diwali", "start": "2026-11-06", "end": "2026-11-10",
                  "days_away": 25, "categories": [{"category": "Dry fruits", "multiplier": 1.62,
                  "label": "learned", "n_occurrences": 1, "applied": true, "evidence": "..." }],
                  "delivery_padding_days": 1 }],
  "sections": {
    "buy": ["<line_id>", ...], "do_not_buy": [...], "watch": [...], "reduce": [...]
  },
  "lines": { "<line_id>": { ...all line fields, product name, supplier name, tags... } },
  "expiry_batches": [{ "product": "...", "batch_no": "...", "expiry_date": "...", "qty": "12.000",
                       "exposure_qty": "9.000", "exposure_value": "540.00", "options": ["sell_first","return_to_supplier"] }],
  "budget": { "budget": "...", "needed": "...", "funded": "...", "shortfall": "...",
              "unfunded_lines": [...], "still_at_risk": [...], "weights": {...} },
  "data_notes": [{ "code": "MISSING_LEAD_TIME", "severity": "warning", "message": "...", "count": 2, "entities": [...] }],
  "backtest_summary": { "tenant_wape": 0.31, "bias": -0.02, "baseline_wape": 0.36, "by_segment": [...] }
}
```

The lines are duplicated in `recommendation_lines` (normalised, for filtering and joins). The snapshot is what exports and the report page read for the headline view.

## 4. PDF layout (ReportLab)

- A4 portrait, margins 16 mm. Fonts: IBM Plex Sans (Regular, Medium, SemiBold) and Plex Mono, registered from `assets/fonts/` so the Rupee sign renders. Test that the glyph appears.
- Header on every page: business name left, "Monday plan, week of 12 Oct 2026" centre, page "n of m" right. Footer: "Data up to 11 Oct 2026. Generated 12 Oct 2026, 6:02 am." and, when synthetic, "Demo data. Numbers are simulated." in the footer and as a light strip below the header.
- Page 1: Summary block (six key numbers), top five critical lines, festival note, budget bar (drawn with `reportlab.graphics`).
- Then sections 2 to 8 as tables, supplier-grouped for Buy. Long text columns wrap. Repeat header rows on page breaks. Money right aligned, quantities right aligned with unit.
- Use the app colours for risk text (dark red, orange, amber, green) and always print the word, not only the colour.
- Last page: how to read this plan (3 short paragraphs) and assumptions list.
- Target 4 to 8 pages for 120 products.
- Optional filter: supplier, section.

## 5. Excel layout (XlsxWriter)

Sheets in order: `Summary`, `Buy list`, `By supplier`, `Watch`, `Do not buy`, `Reduce exposure`, `Expiry batches`, `Festival`, `Budget`, `Data notes`, `Accuracy`.
- Header row styled (bold, bottom border, fill `#F5F3EE`), freeze panes below header, autofilter, column widths set, numeric formats: money `[$₹-4009]#,##0.00`, quantity `#,##0.###`, percent `0%`, dates `dd mmm yyyy`.
- `Buy list` has live formulas: spend = funded qty times unit cost, totals row with `SUBTOTAL(109, ...)` so filters update totals. A check cell compares formula total to the engine total.
- `By supplier` groups lines with supplier subtotals, one block per supplier, ready to send.
- Provenance column shows `Observed`, `Calculated` or `Assumed` for key fields via cell comments or a separate small column.
- Sheet `Summary` carries business name, week, data cutoff, model version, demo notice.
- No macros, no external links.

## 6. CSV

Two files, UTF-8 with BOM (so Excel opens Rupee text correctly), comma separated, header row, ISO dates, decimals with a dot, no thousands separators.

`purchase_list.csv` columns, in order:
`supplier_code, supplier_name, sku, product_name, pack_size, packs, quantity, unit_cost, line_total, expected_delivery_date, decision, reason`

`plan_lines.csv`: all line fields with machine names (`recommendation_lines` columns), plus product and supplier names.

Rules: only approved and edited lines in `purchase_list.csv` when any decisions exist, otherwise all funded lines with decision `pending`. Quantity uses the decided final quantity.

## 7. File naming and delivery

`backroom_{tenant_slug}_monday-plan_{YYYY-MM-DD}.{pdf|xlsx|csv}`. Exports stream from the API with `Content-Disposition: attachment`, authorised by the bearer token (download through `fetch` and blob, no public URLs). Each export writes an `audit_logs` row (`report.export`).

## 8. Acceptance checks

- Totals on screen, in Excel and in CSV match to the paisa.
- Every line in exports exists in `recommendation_lines`.
- Open the XLSX with `openpyxl` in tests and verify sheet names, formulas present, number formats.
- Extract PDF text in tests and verify business name, week, demo label, and a Rupee sign.
- Regenerating the report for the same cutoff gives identical numbers.
