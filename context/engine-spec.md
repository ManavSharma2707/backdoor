# Engine specification

The engine turns ledger history into a buying plan. It is pure Python in `backend/app/engine/`: functions take dataclasses or DataFrames and an explicit `as_of` date, and return results. No database access, no clock, no globals. Services load inputs and persist outputs. This makes dry-run scenarios, backfills and tests trivial.

Guiding rule from the proposal: use the simplest model that is good enough, and evaluate everything against a baseline.

---

## 1. Definitions

| Term | Meaning |
|---|---|
| `as_of` | The Monday the plan is for (order date). History used: `business_date < as_of`. |
| `data_cutoff` | `as_of` at 00:00 IST. Stored on every run. |
| Demand | `units_sold - units_returned(restocked)` per product per day, on trusted days. |
| Trusted day | `availability_state = 'available'` and not promo-excluded. |
| Censored day | `sold_out_during_day` or `stocked_out_all_day`. Sales on these days understate demand. |
| L | Lead time days (see 6.1). |
| R | Review period days (default 7). |
| P | Protection period = L + R + festival padding. |
| IP | Inventory position. |
| SS | Safety stock. |

## 2. Inputs the pipeline loads

- `daily_product_stats` for the last 400 days (or all history).
- Products, categories, supplier terms (current), suppliers.
- Stock balances per product and batch, open and overdue POs.
- Calendar events and learned effects, promotions, recorded stockout intervals.
- Settings.

Memory discipline: use `float32` where precision allows, process per tenant, and chunk LightGBM feature building by category. Drop frames after use.

## 3. Daily rollup (`services/rollup.py`)

For each product and date since the last rollup:
- `opening_on_hand`, `closing_on_hand` from the ledger (cumulative movements).
- `units_sold`, `units_returned`, `revenue`, `avg_price`, `receipts_qty`.
- `availability_state`:
  - `not_launched` if date < `launched_on`.
  - `stocked_out_all_day` if opening = 0 and no receipts that day (and no sales).
  - `sold_out_during_day` if closing = 0 and units_sold > 0.
  - `available` otherwise.
  - `unknown` if the product had no ledger history before the date (no opening balance).
- A date inside a recorded `stockout_intervals` range forces `stocked_out_all_day` unless sales exist (then `sold_out_during_day`).
- `is_censored = availability_state in (sold_out_during_day, stocked_out_all_day)`.
- `promo_active` from `promotions` covering the product or its category.
- `event_keys` from `calendar_events` windows covering the date.

The rollup is idempotent (upsert) and can be rebuilt for any range.

## 4. Demand classification

Per product, on trusted days of the last 180 days (minimum 28 trusted days, otherwise class `new`):
- ADI = mean gap in days between non-zero demand days.
- CV2 = squared coefficient of variation of non-zero demand sizes.
- Class (Syntetos and Boylan): `smooth` (ADI < 1.32, CV2 < 0.49), `erratic` (ADI < 1.32, CV2 >= 0.49), `intermittent` (ADI >= 1.32, CV2 < 0.49), `lumpy` (ADI >= 1.32, CV2 >= 0.49).
- `new`: fewer than 28 trusted days. `no_history`: fewer than 7.

Segment key: `category_slug|class`. Selection and backtest scoring happen per segment.

## 5. Forecasting

### 5.1 Training series
The window is the last 800 days (`TRAINING_DAYS`, `D-076`). The series is effect adjusted: history is divided by the applied multiplier and the forecast is multiplied back. Lag features of the global model use the same adjusted series.

`y[t]` for trusted days, `NaN` for censored or promo days when `censor_policy = 'exclude'` (default) and `promo_policy = 'exclude'`. All statistical methods compute means over non-NaN values only. Optional `weekday_fill` policy replaces censored days with the weekday-profile estimate, applied only if explicitly set, and always flagged in the report.

Never impute demand silently. If more than 30 percent of the last 56 days are censored, confidence drops one level and the line gets warning `CENSORED_HISTORY`.

### 5.2 Methods (all in `engine/methods/`, same signature `fit_predict(series, horizon_dates, ctx) -> Forecast`)

| Method | Definition | Notes |
|---|---|---|
| `seasonal_naive` | `y[t-7]`, falling back to the weekday mean if missing | Baseline |
| `moving_average` | Mean over last `w` trusted days, `w` in {14, 28, 56} (56 for intermittent) | Baseline, parsimony anchor |
| `weekday_profile` | `level` = mean over last 8 weeks. `idx[d]` = mean(y on weekday d) / level, shrunk: `idx = 1 + (idx_raw - 1) * n_d / (n_d + 4)`. Forecast = `level * idx[weekday]` | Needs 6 or more weeks |
| `ses_weekday` | Deseasonalise by `idx`, run simple exponential smoothing on the deseasonalised series, `alpha` from grid {0.05, 0.1, 0.2, 0.3, 0.5} by lowest one-step in-sample MAE, reseasonalise | Custom numpy, no statsmodels. Deseasonalises with the raw weekday index (`D-078`) |
| `croston_sba` | Croston with Syntetos-Boylan bias correction (factor `1 - alpha/2`), `alpha = 0.1`, daily rate = size / interval | For intermittent and lumpy |
| `lightgbm_global` | One model per tenant, features below | Full profile only |
| `category_prior` | Category mean per product-day times 0.8 | Only for `new` and `no_history`, always `confidence = low`, provenance `assumed` |

### 5.3 LightGBM global model
- Trained per tenant on rows `(product, origin, horizon h)`, origins weekly over the last 70 weeks, `h` in 1..28 (sample every origin, all horizons).
- Features (all known at the origin): lags 7, 14, 21, 28 and rolling means 7, 28, 56 of demand (trusted days only), rolling zero-share 28, weekday of target, day of month, month, week of year, `h`, days since last sale, product age in days, price ratio to 90 day average, `promo_flag` of target date, event features (for each event_key in the calendar: is-in-pre, is-in-during, is-in-post flags of the target date, plus days to next major festival), category id (categorical), product mean level and CV (from history), availability share last 28 days.
- Objective `tweedie` (variance power 1.2) or `poisson`, chosen by validation MAE. `n_estimators 300`, `learning_rate 0.05`, `num_leaves 31`, `min_data_in_leaf 50`, `feature_fraction 0.8`, `bagging_fraction 0.8`, `n_jobs 1`, `seed 42`.
- Excluded rows: target dates that are censored or promo-excluded (no label).
- Backtest uses 4 origins (weeks -4 to -1), retraining per origin. Time cap 5 minutes per tenant, otherwise skip LightGBM and record `lgbm_skipped` in run config.
- Event effects are inherent to LightGBM through event features. Do not multiply LightGBM forecasts by learned event multipliers.

### 5.4 Event and promotion modifiers (statistical methods only)
See section 7. `forecast_d = base_d * m(category, d)` where `m` defaults to 1.

### 5.5 Horizon and output
Forecast `H = forecast_horizon_days` (28). Store `yhat`, `yhat_lower`, `yhat_upper` (80 percent interval from backtest residual quantiles of the selected method, per segment, scaled by `yhat / segment_mean`; floor at 0). Clip forecasts at 0. Round only for display.

## 6. Backtesting and selection

### 6.1 Protocol
- Rolling origin: weekly origins over the last `backtest_origins` (12) weeks for statistical methods, 4 for LightGBM. At each origin, fit on data before the origin, forecast the next 7 days (and 28 for LightGBM horizon check), compare with actuals on **trusted days only**.
- Metrics per product, aggregated to segment and tenant: `MAE`, `RMSE`, `WAPE = sum|e| / sum(actual)` (null if sum actual is 0), `bias = sum(f - a) / sum(a)`, `coverage_ratio` (trusted target days / all target days).
- WAPE is reported only for `smooth` and `erratic` segments. For intermittent and lumpy segments report MAE and bias, and show "WAPE not meaningful" in the UI.
- Baselines are always `seasonal_naive` and `moving_average` (28).

### 6.2 Selection per segment
1. Candidate set by class: smooth and erratic: all methods except Croston. Intermittent and lumpy: `moving_average` (56), `croston_sba`, `weekday_profile`, `lightgbm_global`. New: `moving_average` on available data, else `category_prior`.
2. Score = segment-level MAE (sum of absolute errors divided by number of points).
3. Winner = lowest score. If the winner improves on `moving_average` by less than 3 percent, choose `moving_average` (parsimony). Record all scores in `forecast_backtests`, mark the winner `is_selected`.
4. Segments with fewer than 3 products or fewer than 200 backtest points fall back to the tenant-level selection among the same class, then to `moving_average`.
5. Selection is stored (metrics quantised to the stored precision, `D-078`). With no stored selection the light profile runs an in memory statistical backtest and stores it. Light profile reuses the last selection if it is less than 35 days old, otherwise falls back to the best non-LightGBM method of the stored scores.

### 6.3 Synthetic ground truth check
For synthetic tenants only, `scripts` compare each selected forecast with `synthetic_true_demand` over the last 12 weeks and write a markdown table (`backend/tests/reports/synthetic_accuracy.md`). This shows how censoring affects measured accuracy. Report it honestly, including where the model loses to a baseline.

### 6.4 Confidence label per product line
Inputs: coverage (trusted share of last 90 days), selected method WAPE (or MAE ratio for intermittent), class, product age, censored share.
- `high`: coverage >= 0.80, class smooth or erratic, WAPE <= 0.35, not new, censored share <= 0.15.
- `medium`: coverage >= 0.60 and (WAPE <= 0.60 or intermittent with MAE/mean <= 1.0), not `new`.
- `low`: everything else, `new`, `no_history`, `category_prior`.
- Downgrade one level for: missing or assumed lead time, `CENSORED_HISTORY`, supplier overdue PO, forecast based on `lightgbm_skipped` fallback.
Thresholds live in `engine/constants.py` and are listed in `memory.md`.

## 7. Event effects (festivals, seasons, promotions)

Calendar from `calendar_events` (see `india-calendar.md`). Windows for event occurrence `o`: `pre = [start - pre_days, start - 1]`, `during = [start, end]`, `post = [end + 1, end + post_days]`. Seasons use `during` only.

### 7.1 Learning
For each tenant, `event_key`, category, window:
1. For every past occurrence `o` fully inside history, for each product `p` in the category with at least 70 percent trusted days in the window and in the baseline period:
   - baseline = weekday-profile expectation for the window days, fitted on the 8 weeks before the occurrence's `pre` window start, excluding days inside other event windows.
   - `ratio_p = sum(actual on window days) / sum(baseline on window days)`.
2. Category ratio = baseline-volume-weighted median of `ratio_p`.
3. `consistency` = volume share of products whose `ratio_p` points the same way as the median and deviates more than 5 percent.
4. Combine occurrences by averaging log ratios. `n_occurrences` = number of usable past occurrences.
5. Shrink: `m = 1 + (m_raw - 1) * n / (n + 0.5)`. Clip to [0.5, 3.0].

### 7.2 Application gate (all must hold, else `is_applied = false`)
- `n_occurrences >= 1`, `n_products >= 3`, window length >= 3 days (during) or any for pre and post.
- `abs(m - 1) >= 0.15`.
- `consistency >= 0.60`.
- **Significance** (added in Prompt 4, `D-075`): a Stouffer z-test of the product log ratios against the dispersion measured in the baseline weeks, then Benjamini-Hochberg false discovery control at 10 percent (`EFFECT_FDR`) across all effects of the tenant. Effects that fail are labelled "not enough evidence".
- **Medical tenants**: festival events apply only if `origin = configured`, or learned with `n_occurrences >= 2` and `consistency >= 0.75`. Seasons follow the normal gate. This enforces "no blanket festival uplift for medicines".

### 7.3 Use
- Learned and applied: multiplier on statistical forecasts for the window days. Label in report: "Learned from last year, n occurrence(s)". Confidence `medium` for one occurrence, `high` for two or more with consistency >= 0.75.
- Configured (owner entered): multiplier applies, provenance `assumed`, label "Set by you".
- Overlapping windows on one date: use the multiplier with the largest `abs(ln m)`. No compounding.
- Not applied but computed: still shown in the Festival insights with the text "Not enough evidence to adjust forecast", and the evidence numbers.
- Promotions: learned per category the same way under `event_key = 'promotion'` (ratio on promo days versus baseline). Applied to horizon days where a promotion row covers the product or category. If fewer than 2 past promotions in the category, no uplift is applied and the line carries warning `PROMO_UPLIFT_UNKNOWN`.

### 7.4 Festival delivery padding
`delivery_delay_days` from events whose `pre` or `during` window overlaps `[as_of, as_of + L]`. Padding = max of those values, added to L when `apply_festival_lead_padding` is true. Source label "Festival delay".

## 8. Inventory state (`inventory_state.py`)

Per product at `as_of`:
- `batches`: `[(batch_id, qty, expiry_date, unit_cost)]` from `stock_balances`, excluding `quarantined`, expired (expiry <= as_of) and zero quantity. Non-batch products have one pseudo batch with no expiry (or product-level shelf life if tracked loosely).
- `on_hand_total`: sum including expired for display, `on_hand_sellable`: excluding expired and quarantined.
- `reserved`: sum of `reserved_qty`.
- `incoming`: open PO lines (`sent`, `partially_received`) with `qty_open = ordered - received`.
  - `confirmed`: expected_date >= as_of and status in (sent, partially_received).
  - `overdue`: expected_date < as_of. Excluded from confirmed incoming, reported as `incoming_excluded_overdue`, line warning `PO_OVERDUE`. Draft and cancelled POs never count.
  - Arrival date of each confirmed PO = `expected_date` (if later than `as_of + L`, it still counts toward P but not toward L coverage).
- Last count date, last receipt date.

## 9. FEFO expiry simulation (`expiry.py`)

`simulate_fefo(batches, daily_forecast, arrivals, horizon_days)`:
1. For day d in `as_of ... as_of + horizon`: expire any batch with `expiry_date <= d` (move remaining qty to `lost`), add arrivals, then consume `forecast[d]` from the batch with the earliest expiry, then next.
2. Return per batch: `expected_sold`, `expected_loss` (unsold at expiry), and per day stock.
3. For batches expiring after the horizon: extrapolate with the average daily forecast over the last 14 horizon days to the expiry date (cap at 365 days), then compute expected loss.
4. `expiry_exposure_qty` = sum of expected loss. `expiry_exposure_value` = loss quantity times the batch unit cost (average cost for non-batch).
5. `expected_expiry_loss` is subtracted from usable on-hand in the inventory position because those units will not serve demand.

Near expiry list: batches with `days_to_expiry <= near_expiry_days` showing batch id, quantity, expiry date, exposure quantity and value. Already expired: `expiry_date <= as_of` and quantity > 0, flagged `WRITE_OFF_NEEDED`, excluded from usable.

## 10. Replenishment (`replenishment.py`)

For each active product with a primary supplier term (or a fallback supplier). Notation uses calendar days from `as_of`.

### 10.1 Lead time and protection period
```
L_term    = supplier_product_terms.lead_time_days
L_default = suppliers.default_lead_time_days
L_base    = L_term ?? L_default ?? settings.default_lead_time_days   (source recorded; business default is "assumed")
L_eff     = days from as_of until the first supplier delivery weekday on or after as_of + L_base
            (if delivery_weekdays is null, L_eff = L_base)
L         = L_eff + festival_padding
P         = L + R
```

### 10.2 Demand and position
```
D_L = sum(forecast[as_of ... as_of+L-1])                 demand before the new order can arrive
D_P = sum(forecast[as_of ... as_of+P-1])                 demand to cover
usable     = on_hand_sellable - expected_expiry_loss
IP         = usable + incoming_confirmed - reserved
```

### 10.3 Safety stock
```
sigma_day = RMSE of daily forecast errors of the selected method for this product (from backtests),
            fallback: segment RMSE scaled by product mean / segment mean,
            fallback: max(std of trusted demand, 0.5 * mean)     (flag as assumed)
z         = NormalDist().inv_cdf(service_level)
SS        = z * sigma_day * sqrt(P)
target    = max(D_P + SS, min_stock_qty)
```
Use `statistics.NormalDist`, no scipy.

### 10.4 Raw, MOQ, pack, expiry cap
```
raw = max(0, target - IP)
if raw > 0:
    units = max(raw, moq_units)
    packs = ceil(units / pack_size)
    suggested = packs * pack_size
    pack_excess = suggested - raw
else: suggested = 0
```
**Expiry cap** for batch tracked products with `shelf_life_days`:
```
cap_days = min(shelf_life_days * sellable_shelf_life_fraction, 120)
cap_qty  = sum(forecast over the next cap_days) - IP    (floor 0)
if suggested > cap_qty rounded up to pack: reduce to that, add reason EXPIRY_CAP
```
If the cap forces the quantity below MOQ, order 0 and add warning `MOQ_VS_SHELF_LIFE`.

**Pack rounding mode** `nearest_safe` (optional): if `pack_excess > 0.5 * pack_size` and `usable + incoming >= D_L + 0.5 * SS`, round down instead of up. Default is `up`, as in the proposal example.

Worked example (must be a unit test): forecast 3 per day, P = 10, D_P = 30, usable 12, incoming 5, SS 4, pack 10 -> raw = 30 + 4 - 17 = 17 -> suggested 20, pack excess 3.

### 10.5 Spend
`est_spend = suggested * unit_cost` where `unit_cost` = primary term price effective on `as_of`. If missing, `est_spend = null`, warning `MISSING_COST`, and the line cannot be funded or turned into a PO until fixed.

## 11. Risk (`risk.py`)

Arrival `A = as_of + L`. Stock available to serve demand before arrival: `S_L = usable + incoming arriving on or before A - reserved`.
```
sigma_L  = sigma_day * sqrt(L)
p_stockout = 1 - Phi((S_L - D_L) / sigma_L)        if sigma_L > 0, else 1 if S_L < D_L else 0
projected_stockout_date = first date where cumulative forecast exceeds usable + arrivals so far (None if none within horizon)
days_of_cover = usable / avg_daily_forecast over next 14 days (None if avg is 0)
```
| Level | Condition |
|---|---|
| `critical` | out of stock now (usable = 0 and forecast > 0), or `p_stockout >= 0.60`, or projected stockout date <= A |
| `high` | `0.30 <= p_stockout < 0.60` |
| `medium` | `0.10 <= p_stockout < 0.30`, or `p_stockout > 1 - service_level`, or IP < D_P + SS with `p_stockout < 0.10` |
| `low` | `p_stockout < 0.10` and an order is suggested |
| `none` | no order needed and `p_stockout < 0.10` |

A line tagged `watch` if risk is critical or high, or has `PO_OVERDUE`, or confidence is low with risk medium or above. Note that a stockout before delivery cannot be fixed by ordering now: the line says so ("Likely to run out before the next delivery on 14 Oct").

## 12. Budget allocation (`budget.py`)

If `weekly_budget` is null: allocated = suggested, no limit. Otherwise:

1. `needed = sum(est_spend)` over lines with `suggested > 0` and a known cost.
2. If `needed <= budget`: allocated = suggested.
3. Else score each line, components normalised to [0, 1]:
   - `risk` = `p_stockout`.
   - `value` = percentile rank of `expected_margin = min(D_P, suggested) * (selling_price - unit_cost)` among lines.
   - `confidence` = high 1.0, medium 0.7, low 0.4.
   - `excess` = `(pack_excess + expiry_exposure_qty) / max(suggested, 1)` clipped to [0, 1].
   - `score = w_risk * risk + w_value * value + w_conf * confidence - w_excess * excess` with weights from settings.
4. Sort by score descending (ties: higher `p_stockout`, then lower spend). Greedy fill:
   - If full `suggested * cost` fits remaining budget: allocate it.
   - Else allocate the largest whole number of packs that fits and satisfies MOQ. If none fits, allocate 0.
   - Continue to the next line (small lines can still fit).
5. For each line: `allocated_qty`, `unfunded_qty = suggested - allocated`, `budget_limited = unfunded_qty > 0`. If a critical line is unfunded add warning `CRITICAL_UNFUNDED`.
6. Budget view: budget, planned spend, shortfall (`needed - budget`), count and value of unfunded lines, list of lines still at critical or high risk. **Never claim all demand is covered when it is not.**

Priority components are stored in `priority_components`.

## 13. Sections and stock status (`deadstock.py`, `report_builder.py`)

Section tags per line (a line can carry several):
- `buy`: `allocated_qty > 0` (or `suggested > 0` when unconstrained).
- `do_not_buy`: `suggested = 0` and `days_of_cover >= L` (adequate coverage), with the reason "Covered for N days".
- `watch`: see section 11.
- `reduce`: stock status slow, non_moving, or excess > 0, or expiry exposure > 0.

Stock status (checked in order):
- `new`: product age < `nonmoving_days` or class `new`.
- `non_moving`: no sale in `nonmoving_days`, and available share of that window >= 0.70, and not (`is_seasonal` and out of season), and on-hand > 0.
- `unverified`: zero sales in `nonmoving_days` but available share < 0.70 or missing transactions suspected. Shown as "Check before calling this dead stock".
- `slow`: `days_of_cover >= slow_cover_days` and has sales in the window.
- `normal`: otherwise.

Excess: `excess_qty = max(0, IP - (D_(P + excess_horizon_days) + SS))`, `excess_value = excess_qty * avg cost`.

ABC (insights): by revenue share over the last 90 days: A top 70 percent, B next 20, C last 10.

## 14. Data quality checks (`dq.py`)

Each check yields `data_quality_issues` rows (code, severity, entity, message, fix hint). Severity `error` blocks nothing but is shown at the top of the report.

| Code | Severity | Trigger |
|---|---|---|
| `MISSING_LEAD_TIME` | warning | no lead time at term, supplier or business level (business default used) |
| `MISSING_COST` | error | no purchase price for primary supplier |
| `MISSING_SUPPLIER` | error | active product without primary supplier term |
| `MISSING_EXPIRY` | error | batch tracked product with on-hand quantity in a batch lacking expiry |
| `STALE_STOCK_COUNT` | warning | no count in `stale_count_days` for A class products |
| `NEGATIVE_STOCK` | error | any balance below zero (should be impossible, defensive) |
| `BATCH_QTY_MISMATCH` | error | balance differs from ledger sum |
| `RECEIPT_EXCEEDS_ORDER` | warning | exception receipts in the last 30 days |
| `PO_OVERDUE` | warning | open PO past expected date |
| `SPARSE_HISTORY` | info | fewer than 28 trusted days |
| `NEW_PRODUCT` | info | age under `nonmoving_days` |
| `CENSORED_HISTORY` | warning | over 30 percent censored in last 56 days |
| `UNRECORDED_STOCKOUT_SUSPECTED` | info | inferred zero-stock intervals longer than 2 days with no recorded interval |
| `DUPLICATE_SALE_SUSPECT` | info | identical basket and total within 2 minutes |
| `PRICE_ANOMALY` | warning | purchase price changed more than 30 percent between terms, or selling price below cost |
| `ZERO_SALES_UNVERIFIED` | info | see `unverified` stock status |
| `CALENDAR_STALE` | warning | no event in the next 60 days |
| `PROMO_UPLIFT_UNKNOWN` | info | promotion in horizon without learned uplift |
| `MOQ_VS_SHELF_LIFE` | warning | cap below MOQ |

A line shows only the issues that concern its product. Issues with no resolution path are explained in the "Data and confidence notes" section.

## 15. Monday pipeline (`pipeline.py`, called by `jobs/monday.py`)

```
run_pipeline(tenant_id, as_of, profile: light|full, overrides: Overrides | None, persist: bool)
```
Steps:
1. Lock: session level `pg_try_advisory_lock` per tenant (a second run is skipped). The persist step is one transaction, `job_runs` rows are written in their own transactions. Insert `job_runs` (key `monday_report:{as_of}`), skip with `skipped` if already `succeeded` and no `force`.
2. DQ checks (pre).
3. Rollup up to `as_of - 1`.
4. Refresh effects (learn) if older than 7 days or `full`.
5. Backtest and selection if `full` and last selection older than 7 days (or none).
6. Forecast run (`weekly`), store values.
7. Inventory state, FEFO simulation.
8. Replenishment lines, risk, stock status, excess.
9. Budget allocation.
10. Build report snapshot and sections.
11. Persist in one transaction: forecast run, recommendation run and lines, weekly report (version bump if regenerate), DQ issues. On any exception roll back, mark `job_runs` failed with the error, log.
12. Retention: prune `forecast_values` older than 8 runs and `idempotency_keys` older than 48 hours.
13. If agents enabled: run Monday Analyst (separate transaction). Failure is recorded, report still `ready`.
14. Mark `job_runs` succeeded with timings.

Retry safety: the whole persist step is one transaction guarded by the advisory lock and the unique `(tenant_id, week_start) WHERE is_current` index. Running twice produces one current report unless `force` is set, then version + 1.

`Overrides` for dry-run scenarios: `weekly_budget`, `service_level`, `review_period_days`, `lead_time_delta_by_supplier`, `supplier_delay_days`, `excluded_product_ids`, `forced_include_ids`. Scenario runs reuse the latest stored forecast values and inventory state, skip persistence, and return metrics: planned spend, number of critical and high lines, expected units short (normal loss function: `sigma * (phi(z) - z * (1 - Phi(z)))`), expiry exposure value, unfunded value.

`as_of` backfill: `python -m app.jobs.run backfill --weeks 8` runs the pipeline for past Mondays with `profile=light` and the data cutoff of each date, so insights show forecast versus actual and decision memory has history.

## 16. Module and test map

| Module | Tests (all pure unit and property tests) |
|---|---|
| `methods/*` | known series give known outputs, NaN handling, nonnegative, empty series |
| `demand_class` | synthetic series for all four classes |
| `event_effects` | planted uplift recovered within 10 percent, gate rejects noise, medical stricter gate |
| `backtest` | no lookahead (shuffle future values, forecasts unchanged), metrics math |
| `expiry` | FEFO order, loss when demand too low, expired excluded |
| `replenishment` | worked example, MOQ and pack, hypothesis: `suggested >= raw`, multiple of pack, never negative |
| `budget` | spend never exceeds budget, higher score funded first, partial packs |
| `risk` | boundaries of each level |
| `pipeline` | determinism: same inputs give identical output (golden JSON per fixed seed) |
