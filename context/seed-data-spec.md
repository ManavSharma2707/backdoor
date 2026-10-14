# Seed data specification

Goal: four believable Indian retail businesses, simulated day by day, that behave like real shops and exercise every engine path. Deterministic, reconciled, labelled synthetic. The demo data proves the workflow works. It never proves real-world savings.

---

## 1. Tenants

| Key | Slug | Display name | Type | SKUs | Story |
|---|---|---|---|---|---|
| `fmcg_a` | `shree-sai-kirana` | Shree Sai Kirana and General Stores | fmcg | 92 | Small neighbourhood grocery. Tight cash, weekly budget about 70 percent of unconstrained need, frequent stockouts, strong monthly ration pattern, Ganesh Chaturthi and Diwali uplifts |
| `fmcg_b` | `mahalaxmi-super-mart` | Mahalaxmi Super Mart | fmcg | 118 | Mid-size supermarket. Many promotions, overstock in two categories, more suppliers, larger baskets, higher volume |
| `med_a` | `sanjivani-medical` | Sanjivani Medical and General | medical | 150 | Neighbourhood pharmacy, chronic-medicine heavy, steady refills, FEFO story, few near-expiry batches |
| `med_b` | `aarogya-care-pharmacy` | Aarogya Care Pharmacy | medical | 152 | Clinic-adjacent, acute and OTC mix, intermittent demand, monsoon illness pattern, large expiry exposure story |

All names are fictional. Names are common words, so check the spelling does not match a real chain before publishing screenshots. All four are in Maharashtra, but **no location appears anywhere in the UI, account names, exports or data**. Festival calendar and patterns are Maharashtra flavoured. Owners:

| Tenant | Owner name | Email |
|---|---|---|
| `fmcg_a` | Ramesh Kulkarni | `owner.fmcg-a@backroom-demo.com` |
| `fmcg_b` | Sunita Deshmukh | `owner.fmcg-b@backroom-demo.com` |
| `med_a` | Anil Joshi | `owner.med-a@backroom-demo.com` |
| `med_b` | Pooja Patil | `owner.med-b@backroom-demo.com` |

The password comes from env `DEMO_OWNER_PASSWORD` (the seed refuses to run without it, minimum 12 characters). No password is stored in the repo. Emails are never sent to.

## 2. Time frame

- History: Monday `2025-04-14` to Sunday `2026-10-11` inclusive (546 days, 78 weeks). Parameter `--end-date` defaults to `2026-10-11` and must be a Sunday. Start = end minus 545 days.
- Opening balances dated `2025-04-13` (movement `opening`).
- First Monday plan is for `as_of = 2026-10-12`. Eight retrospective plans are backfilled for Mondays `2026-08-17` to `2026-10-05` (the engine run as of each date, light profile) with synthetic decisions.
- History covers: Raksha Bandhan, Ganesh Chaturthi, Navratri and Dussehra, Diwali (2025), Christmas and New Year, Makar Sankranti, Holi, Gudi Padwa, Eid al-Fitr, Eid al-Adha 2026, monsoon 2025 and 2026, winter, summer. The forecast window ahead includes Navratri and Dussehra 2026 and Diwali 2026 (6 to 10 Nov). See `india-calendar.md`.
- `simulate_week` appends one more week using the same engine of simulation, continuing state.

## 3. Reproducibility

- `numpy.random.Generator(PCG64(seed))`. Seed per tenant: `base_seed + tenant_index`, `base_seed` default 20261011. Same inputs give byte identical data. Never use `random` module or time based seeds.
- All generators are pure functions of `(tenant profile, date, rng state)`.
- Catalogues are YAML files in `backend/seed/catalogs/` so they are reviewable. The generator reads them. Prompt 3 creates them from the category tables below.

## 4. Volume targets

The first full run of the original targets (2.4, 2.9, 1.7 and 1.9 lines per bill) came to 391 MB after compaction, which left no room for the Prompt 4 tables (`D-067`). Lines per bill were lowered, bills per day were kept.

| Tenant | Bills per day (avg) | Lines per bill (avg) | Lines per day | History lines (actual) | Bills (actual) |
|---|---|---|---|---|---|
| fmcg_a | 55 | 2.0 | about 110 | 59,138 | 29,404 |
| fmcg_b | 110 | 2.4 | about 264 | 144,078 | 58,588 |
| med_a | 55 | 1.4 | about 77 | 43,182 | 28,856 |
| med_b | 90 | 1.55 | about 140 | 78,048 | 47,449 |

Totals as built: 324,446 sale lines, 164,297 bills, 345,850 movements, 279,552 daily stat rows and 279,552 true demand rows. `--scale 0.5` halves the volume for quick runs. `size_report.py` shows 359.0 MB for the tables and indexes (370 MB for the database on disk), under the 400 MB limit.

Bill times: FMCG peak 9 to 11 am and 5 to 9 pm, quiet 2 to 4 pm. Medical peak 10 am to 1 pm and 6 to 9 pm. Shops closed on no day except selected holidays (Diwali Lakshmi Puja evening, Holi afternoon): reduce volume to 40 percent, not zero.

## 5. Categories and SKU counts

### FMCG (fictional brands, realistic Indian packs)

| Category | A | B | Pack and price band (MRP, Rupees) | Shelf life | Demand base (units per day per SKU) | Notes |
|---|---|---|---|---|---|---|
| Atta, rice and grains | 8 | 10 | 1 to 25 kg bags, 45 to 1,400 | 6 to 12 months | 1 to 6 | Month start spike (ration) |
| Pulses and dal | 7 | 8 | 500 g and 1 kg, 70 to 260 | 12 months | 1 to 4 | Month start spike |
| Edible oils and ghee | 5 | 7 | 500 ml to 5 l, 110 to 1,400 | 9 to 12 months | 1 to 4 | Price change event, winter ghee lift |
| Sugar, salt and jaggery | 4 | 5 | 500 g to 5 kg, 20 to 260 | 12 to 24 months | 2 to 5 | Diwali sweets lift for sugar |
| Spices and masalas | 7 | 9 | 50 g to 500 g, 25 to 380 | 12 months | 1 to 3 | Steady |
| Tea and coffee | 4 | 6 | 100 g to 1 kg, 60 to 700 | 12 months | 1 to 4 | Monsoon and winter lift |
| Biscuits and cookies | 7 | 9 | 50 g to 500 g, 10 to 160 | 6 to 9 months | 3 to 12 | Monsoon lift, promotions |
| Namkeen and snacks | 6 | 7 | 30 g to 400 g, 10 to 220 | 3 to 6 months | 2 to 8 | Diwali faral lift, weekend lift |
| Chocolates and sweets | 4 | 6 | 10 g to 250 g, 5 to 450 | 6 to 12 months | 1 to 6 | Diwali, Raksha Bandhan, Christmas |
| Dry fruits | 4 | 6 | 100 g to 1 kg, 90 to 1,800 | 6 months | 0.3 to 2 | Diwali pre-window strong, winter lift |
| Beverages | 6 | 8 | 200 ml to 2 l, 10 to 120 (includes packaged water, juices, soft drinks) | 3 to 9 months | 2 to 10 | Summer lift, soft drinks 40 percent GST |
| Packaged foods | 6 | 8 | noodles, ready mixes, sauces, cereals, 10 to 450 | 6 to 12 months | 1 to 5 | Monsoon lift for noodles |
| Dairy and eggs (packaged) | 3 | 5 | UHT milk, butter, paneer, cheese, 25 to 600 | 30 to 180 days | 1 to 5 | Short shelf life, dated batches |
| Personal care | 8 | 9 | soap, shampoo, toothpaste, oil, 10 to 500 | 24 to 36 months | 1 to 5 | Steady, promotions |
| Home care | 6 | 8 | detergent, dishwash, floor cleaner, 20 to 650 | 24 months | 1 to 4 | Pre-Diwali cleaning lift |
| Festival and puja items | 4 | 5 | agarbatti, camphor, diyas, rangoli colours, puja oil, 10 to 250 | 12 to 36 months | 0.2 to 3 | Strong festival windows, near zero off season |
| Baby and misc | 3 | 2 | diapers, stationery, 20 to 800 | 24 months | 0.3 to 1.5 | Intermittent |
| **Total** | **92** | **118** | | | | |

### Medical (fictional brand names, real generic names, no dosing data stored)

| Category | A | B | Demand pattern |
|---|---|---|---|
| Analgesics and antipyretics | 10 | 10 | Steady OTC, fever lift in monsoon |
| Antibiotics (oral, topical) | 12 | 12 | Acute, intermittent, flu season lift. Schedule H flag on many |
| Antidiabetics | 10 | 7 | Chronic refill, month start lift |
| Cardiac and antihypertensives | 12 | 8 | Chronic refill, month start lift |
| Gastrointestinal and antacids | 10 | 11 | Steady, monsoon lift |
| Respiratory, cough and cold | 10 | 14 | Monsoon and winter lift |
| Antiallergics | 5 | 7 | Seasonal |
| Vitamins and supplements | 12 | 12 | Steady, winter lift |
| Dermatology | 8 | 10 | Monsoon fungal lift, winter dryness lift |
| Eye, ear and oral care | 5 | 6 | Intermittent |
| First aid and dressings | 8 | 8 | Intermittent |
| Baby care | 6 | 6 | Steady |
| Women's health (OTC) | 4 | 5 | Steady |
| Devices and diagnostics | 8 | 6 | Rare, long shelf life or none, glucometer strips have expiry |
| ORS, electrolytes and hydration | 4 | 6 | Summer and monsoon lift |
| Pain relief topicals | 5 | 8 | Steady, winter lift |
| Thyroid and other chronic | 7 | 3 | Chronic refill |
| Personal hygiene and sanitisers | 4 | 5 | Steady |
| Ayurvedic and wellness | 5 | 5 | Steady, winter lift |
| Nutrition and diabetic-friendly foods | 5 | 3 | Steady |
| **Total** | **150** | **152** | |

Medical rules: product names are fictional brands with generic name and strength as descriptive fields (for example brand "Pyrocet 500", generic "Paracetamol", strength "500 mg", form "Tablet", pack "10 tablets" as one strip). Schedule H or H1 is a flag only. No dosing, no indications, no patient or prescription data anywhere. Prices realistic per strip or bottle, 5 to 900 Rupees.

### GST mapping
Use the structure effective 22 Sep 2025: slabs 0, 5, 18, 40 percent. Representative mapping only, not tax advice: most medicines 5 (some 0), staples such as unbranded grains 0 or 5, packaged namkeen, dry fruits, ghee, butter, personal care basics such as soap, shampoo, toothpaste 5, UHT milk and packaged paneer 0, biscuits, chocolates, detergents 18, aerated soft drinks 40. Record the mapping in the catalogue YAML. Sales lines carry the product's rate at sale time. Sale prices are tax inclusive (MRP), tax portion is computed as `price * rate / (100 + rate)`.

## 6. Suppliers

FMCG: 6 (A) and 8 (B) suppliers: a staples wholesaler, an edible oil distributor, a biscuits and snacks distributor, a beverages distributor, a personal and home care distributor, a dry fruits and festival goods trader, and for B a dairy distributor and a packaged foods distributor. Medical: 5 to 6 distributors: a general stockist, an antibiotics and acute specialist, a chronic and cardiac stockist, a devices and OTC wholesaler, an ayurvedic and wellness trader.

Per supplier parameters (all random within bands, fixed per tenant): lead time 1 to 4 days (FMCG), 1 to 3 (medical), delivery weekdays (2 to 5 days of the week, ISO numbers), minimum order value 3,000 to 25,000, payment terms 0 to 30 days, delay probability 8 to 25 percent with delay 1 to 4 days, fill rate 90 to 100 percent, accepts_expiry_returns (medical: mostly true with `expiry_return_window_days` 60 to 90, FMCG: mostly false), return window 3 to 15 days.

Supplier terms per product: purchase price = MRP * margin factor (FMCG 0.80 to 0.92, medicines 0.78 to 0.88, dry fruits 0.85), pack size from the product (FMCG 6, 12, 24, 48 units, kg bags 1 or 5 units, medicines 10, 50, 100 strips), MOQ 0 to 3 packs, lead time null (inherit supplier) for 85 percent, set for 15 percent. A supplier price change event is planted (see scenarios).

## 7. Demand model (true demand, before stock limits)

For product `p` on day `t`:

```
lambda[p,t] = base[p] * weekday[cat, dow] * monthday[cat, dom] * season[cat, month]
              * event[cat, t] * promo[p, t] * price_effect[p, t] * trend[p, t]
true_demand[p,t] ~ NegBin(mean = lambda, dispersion = phi[class])      (Poisson if phi large)
```
Intermittent products use a zero-inflated draw: with probability `1 - q` zero, else NegBin with mean `lambda / q`.

| Factor | FMCG | Medical |
|---|---|---|
| weekday | Sat and Sun 1.15 to 1.35 for snacks, beverages, biscuits. Staples flat. Mon low 0.9 | OTC flat, chronic Mon and Sat slightly higher, Sun 0.8 |
| monthday | Staples, pulses, oil, sugar: days 1 to 7 factor 1.5 to 2.0, days 8 to 20 0.9, days 21 to 28 0.8 (ration shopping). Others flat | Chronic refill: days 1 to 10 factor 1.4, then 0.9 |
| season | Beverages summer (Mar to May) 1.5, monsoon 0.9. Tea monsoon and winter 1.3. Namkeen and biscuits monsoon 1.2. Dry fruits winter 1.4 | Monsoon (Jun to Sep): fever, cold, gastro, dermatology 1.3 to 1.8. Summer: ORS 1.8, hydration 1.5. Winter: cough, cold, vitamins, topical pain 1.3 to 1.5 |
| event | Table below | None. No festival effect on medicines. Optionally 0.6 demand and reduced hours on Diwali Lakshmi Puja day only |
| promo | Promotions table rows: uplift 1.3 to 2.2 during, 0.8 for 5 days after (pull forward) | Rare, 1.2 |
| price_effect | `(price / base_price) ^ -elasticity`, elasticity 0.8 to 1.6 for discretionary, 0.2 to 0.5 for staples | 0.1 to 0.3 |
| trend | Slow drift per product in [-15, +20] percent per year, plus 4 products with a step change | Same |

### FMCG festival effects (multiplier on lambda; ramp shapes)

Pre window ramps linearly from 1.0 to the pre peak, during is flat at peak, post window decays back, then 0.85 dip for 3 days after major festivals for categories that stocked up.

| Event | Category | Pre peak | During | Post |
|---|---|---|---|---|
| Diwali | Dry fruits | 2.2 | 2.6 | 0.8 |
| Diwali | Chocolates and sweets | 1.8 | 2.2 | 0.85 |
| Diwali | Namkeen and snacks | 1.5 | 1.6 | 0.9 |
| Diwali | Home care | 1.5 | 1.2 | 0.9 |
| Diwali | Festival and puja items | 3.0 | 3.5 | 0.4 |
| Diwali | Edible oils and ghee, Sugar | 1.3 | 1.2 | 0.95 |
| Ganesh Chaturthi | Festival and puja items | 2.5 | 3.0 | 0.5 |
| Ganesh Chaturthi | Dry fruits, Sugar, Atta (modak and sweets) | 1.3 | 1.4 | 0.9 |
| Navratri and Dussehra | Festival and puja items | 1.8 | 2.0 | 0.6 |
| Navratri and Dussehra | Dry fruits and sweets | 1.2 | 1.2 | 1.0 |
| Raksha Bandhan | Chocolates and sweets | 1.8 | 2.0 | 0.8 |
| Raksha Bandhan | Dry fruits | 1.3 | 1.3 | 0.9 |
| Gudi Padwa | Sugar, Festival items, sweets | 1.4 | 1.5 | 0.9 |
| Holi | Beverages, sweets, snacks | 1.3 | 1.4 | 0.9 |
| Eid al-Fitr | Dry fruits, sugar, dairy | 1.4 | 1.5 | 0.9 |
| Christmas and New Year | Chocolates, beverages, snacks | 1.3 | 1.4 | 0.9 |
| Makar Sankranti | Sugar and jaggery, sweets, dry fruits | 1.4 | 1.5 | 0.9 |

Per product multipliers get random jitter (plus or minus 15 percent) so categories are consistent but not identical. fmcg_a gets stronger Ganesh and Diwali responses (x1.15), fmcg_b gets stronger promotion responses. Two categories per FMCG tenant are deliberately given **no** effect for some events so that the evidence gate has negative cases (for example namkeen for Holi in fmcg_a).

## 8. Stock, ordering and receipts (the simulated owner)

Daily loop for every tenant:
1. Apply goods receipts due today (actual arrival = expected + delay draw, partial fill per fill rate). Create batches for batch tracked items.
2. Draw true demand, cap by on-hand per product (FEFO batch by batch for batch tracked). Sales beyond stock are lost, flagged in ground truth. If stock hits zero while demand remained, the day is `sold_out_during_day`.
3. Generate bills: assign each product-day sale to bills by sampling basket composition so line counts match the targets, times from the time-of-day profile. Bill numbers `B{YYMM}-{seq:05d}`. Payment modes: FMCG cash 45, UPI 45, card 7, credit 3 percent. Medical cash 35, UPI 55, card 8, credit 2.
4. Returns: 0.6 to 1.2 percent of lines, 80 percent restocked, 15 percent damaged, 5 percent expired (medical: customer returns of sealed items rare, 0.3 percent).
5. Adjustments: random damage or breakage 0.1 to 0.3 percent of products per week, found stock occasionally, expiry write-offs for batches that expired unsold (medical, FMCG dated).
6. Ordering (on each supplier's order weekday, usually 1 to 2 per week): the owner policy for each product with that supplier: `ROP = avg_daily_14d * (L + 3) * noise`, noise lognormal(mean 1.0, sd 0.25). If position (on-hand plus open PO) below ROP, order up to `avg_daily_14d * (L + 10) * noise2`, rounded to packs and MOQ. 8 percent of weeks the owner skips a supplier. 5 percent of orders are mis-sized by plus or minus 40 percent. fmcg_a is cash constrained (cap spend per week to about 70 percent of the above need). Order creates PO `sent` with `expected_date`.
7. Stock counts: every 30 to 45 days a partial count (20 to 30 percent of products), variance -2 to +1 percent of lines, posted as `count_correction`.
8. Stockouts: when a product is out for 2 or more days, record a `recorded` interval with probability 0.6 (the owner remembers). The rest stay unrecorded for the engine to infer.
9. Promotions: per tenant 10 to 14 promotions over the history, 5 to 14 days long, category or product scope, discount 5 to 25 percent, price lowered for the period (selling price drops, `product_prices` rows written).
10. Price changes: MRP increases 2 to 6 percent on about 10 percent of products per year, effective dated.

Opening stock: per product `avg_daily * U(14, 35)` days (batch tracked: 2 to 3 batches with staggered expiry).

## 9. Medical batch rules

- Each receipt creates one batch per product (sometimes two). `batch_no` like `K3A17` (letter-digit pattern, unique per product). Manufactured 2 to 8 months before receipt. Shelf life per product 12 to 36 months from manufacture (devices and strips with expiry vary). Received remaining shelf life is 55 to 90 percent.
- FEFO issue: sell from the earliest expiry batch with stock.
- Near-expiry: designed per tenant (section 10, scenarios S12 to S14).
- Expiry write-offs happen when a batch passes expiry with stock, after a 1 to 10 day delay (owner notices late), recorded as `expiry_writeoff`.
- Supplier returns of near-expiry stock (where policy allows): 20 percent of near-expiry batches are returned in the 30 to 60 days before expiry (`supplier_return` adjustment).
- FMCG dated goods (dairy, namkeen, biscuits, dry fruits, packaged foods) are batch tracked with shorter shelf life. Staples and personal care are not batch tracked.

## 10. Planted scenarios (every one has a test)

IDs are stored in `seed/scenarios.yaml` with the product SKUs picked deterministically, and echoed by `seed.validate` so tests can find them.

| ID | Tenants | Scenario | What the engine must show |
|---|---|---|---|
| S01 | all FMCG | Diwali 2025 category uplift in dry fruits, sweets, puja items | Learned effect for Diwali, applied with one occurrence, label "learned" |
| S02 | all FMCG | One category with no real effect for an event (negative case) | Effect computed, not applied, "not enough evidence" |
| S03 | all | 5 products with recorded stockouts, 5 with unrecorded stockouts | Censored days excluded, `CENSORED_HISTORY` warning on some, recorded intervals respected |
| S04 | fmcg_b, med_b | 6 slow movers with big overstock (bulk deals) | In Reduce exposure, no purchase suggested |
| S05 | all | 3 truly non-moving products (discontinued variant) | `non_moving` status |
| S06 | all | 2 products that look dead because they were out of stock for months | `unverified`, not `non_moving` |
| S07 | all | 1 open PO overdue by 6 or more days with a supplier delay | `PO_OVERDUE`, incoming excluded from confident stock, watch tag |
| S08 | fmcg_a | Budget at about 70 percent of need | Budget view shows shortfall and unfunded lines, critical unfunded warnings |
| S09 | fmcg_b, med_a, med_b | Budget at about 105 percent of need | No shortfall |
| S10 | all | 2 products missing lead time, 1 missing cost, 1 batch tracked product with a batch missing expiry | `MISSING_LEAD_TIME`, `MISSING_COST`, `MISSING_EXPIRY` warnings, reduced confidence, no PO possible for missing cost |
| S11 | all | Supplier price change plus 9 percent on edible oils (FMCG) or a chronic brand (medical) in January 2026 | `PRICE_ANOMALY` only if over 30 percent (so none here), spend uses the new price |
| S12 | med_a | 4 batches within 90 days of expiry, 1 already expired with stock | Expiry list with batch, quantity, value, `WRITE_OFF_NEEDED` |
| S13 | med_b | 14 near-expiry batches, large exposure value, 3 from suppliers that accept returns | High exposure total, operational options with return policy |
| S14 | fmcg_a, fmcg_b | 3 dated products (namkeen, dairy) with expiry exposure | Expiry cap reduces quantity (`EXPIRY_CAP`) |
| S15 | all | 2 new products launched 5 weeks before the end | `new` class, low confidence, category prior |
| S16 | all | 4 products where MOQ or pack size forces a big excess | `PACK_ROUNDING` and `MOQ_APPLIED` reasons |
| S17 | all | 3 products with no count for over 45 days (A class) | `STALE_STOCK_COUNT` |
| S18 | med_a, med_b | Medicines with chronic month-start pattern | Weekday and month patterns, forecast confidence high |
| S19 | med_a, med_b | Monsoon illness lift categories | Season effect learned, applied, label "seasonal" |
| S20 | all | One product with a mid-year step change in demand (+50 percent) | Shows model bias then adaptation in forecast accuracy insight |
| S21 | fmcg_a | Diwali 2026 plan: demand uplift forecast for the upcoming window (as_of 12 Oct, Diwali starts 6 Nov) | Festival section shows upcoming Navratri and Diwali with pre-window extending into the plan horizon |

(Duplicate bill entry, failed Monday job and retry are API and job tests, not seed data.)

## 11. Knowledge corpus (text, generated by templates, no LLM at seed time)

Written to `knowledge_documents` and `knowledge_chunks`. Embeddings are created by `seed.ingest_knowledge` when `GEMINI_API_KEY` is set. Without a key chunks are stored with `embedding = NULL` and retrieval uses text search only. Chunk size 300 to 500 tokens, overlap 50.

| Type | Content | Per tenant |
|---|---|---|
| `supplier_policy` | Per supplier: Terms and returns, Delivery and pricing notes, Festival schedule notes. Wording varies by seeded RNG choosing among 3 to 4 phrasings. **Facts must match the supplier table** (return window days, whether expiry returns are accepted and the window, minimum order value, delivery weekdays, payment terms) | 3 per supplier, about 20 |
| `decision_memory` | One document per synthetic decision that has a reason (edited or rejected lines): "On 14 Sep 2026 you reduced Biscuits 100 g from 40 to 30 packs because of shelf space" | Created during backfill, about 40 to 80 |
| `report_narrative` | A short plain narrative per backfilled weekly report (what was recommended, what changed) generated from the report summary by templates | 9 |
| `product_note` (medical, operational only) | Handling and storage notes such as "Keep cold chain items in the fridge and record opening date" kept generic and operational, plus FEFO policy and quarantine procedure for expired stock. No clinical content | 8 to 12 |
| `app_knowledge` (global) | Glossary (forecast error, bias, buffer stock, days to cover, minimum order, pack rounding, FEFO, non-moving stock), formula explanations from `engine-spec.md` in plain words, how-to guides (record a sale, return, goods receipt, read the Monday plan, approve and edit, export) | About 30 chunks, `tenant_id` null |

All text follows `ui-copywriting.md` (no dashes, plain, Indian English). `check_copy.py` runs over generated corpus text in tests.

## 12. Synthetic retrospective decisions

For the 8 backfilled plans: simulate the owner. Approve 70 percent of lines as is, edit 20 percent (quantity changed by minus 10 to 40 percent, reason from a list: shelf space, supplier issue, cash tight, already ordered, demand change expected), reject 10 percent. Store as `recommendation_decisions` with `created_at` on that Monday. These do not create POs (history already has its own). Decisions are flagged by tenant `is_synthetic`.

## 13. Output tables written

All tables in `database.md` that apply: tenants, users, settings, categories, products, product_prices, suppliers, terms, promotions, batches, sales, sale_lines, returns, return lines, purchase orders and lines, receipts and lines, movements, balances, counts, adjustments, stockout intervals, daily stats (by running the rollup), `synthetic_true_demand`, calendar events and tax rates (reference), backfilled forecast runs, recommendation runs, lines, decisions, weekly reports, DQ issues, knowledge.

## 14. Implementation notes

- Generate per tenant in memory with NumPy by day, then bulk load with `COPY` (psycopg `cursor.copy`) in dependency order. Disable per-row triggers. Wrap each tenant in one transaction. Rebuild `stock_balances` from movements at the end, then assert equality with the simulation's final state.
- Memory: keep per-tenant arrays as `float32`/`int32`, free after load. Peak under 1.5 GB locally.
- Runtime target: under 10 minutes for all four tenants locally, under 25 minutes against Supabase from a laptop.
- CLI:
  ```
  python -m seed.run --tenants all|fmcg_a,... [--scale 1.0] [--end-date 2026-10-11] [--seed N] [--reset] [--no-backfill] [--no-knowledge]
  python -m seed.validate [--tenants all] [--scale 1.0] [--skip-sim]   # ledger, FEFO, scenarios, rollup checks
  python -m seed.size_report
  python -m seed.realism           # writes seed/realism_report.md
  python -m seed.checksum --tenants all --twice   # determinism
  python -m seed.catalog.builder   # rewrites seed/catalogs/*.yaml
  python -m seed.ingest_knowledge  # embeddings (Prompt 7)
  python -m app.jobs.simulate_week (Prompt 4)
  ```
- `--reset` drops tenant data for the chosen tenants in FK-safe order (never touches other tenants, never the audit log) and refuses to run if `APP_ENV=production` unless `ALLOW_DEMO_RESET=true`. The order comes from the foreign keys in the database. After a reset the large tables get `VACUUM FULL`, otherwise the deleted rows keep using space (473 MB instead of 359 MB).
- The package is `backend/seed` and the command is `python -m seed.run` (`D-065`).

## 15. Validation (`seed.validate`, also run in tests with `--scale 0.1`)

1. The three reconciliation queries in `database.md` return zero rows.
2. Per tenant, daily closing stock from the simulation equals the ledger-derived closing stock for 20 random products on 20 random days.
3. No negative balance at any date (replay the ledger).
4. Every receipt line within its open PO quantity (except flagged exceptions).
5. Batch quantities nonnegative, FEFO respected (no sale from a later batch while an earlier batch had stock, except planted overrides).
6. Counts: SKU totals per tenant match section 5. Category counts match.
7. All planted scenarios exist and are discoverable in `seed/scenarios.yaml`.
8. Determinism: two runs with the same seed produce identical checksum of the key tables.
9. Realism checks printed as a report: average bills per day, share of zero-sale days by class, festival lift ratios, weekday profile, share of days stocked out (target 2 to 6 percent for fmcg_a, 1 to 3 for others).
10. Size report under 400 MB.

---

## 16. As built in Prompt 3

### 16.1 Measurements (full seed, 2026-10-14)

| Item | Value |
|---|---|
| Generation in memory, all four tenants | about 35 to 45 seconds |
| Bulk load per tenant (COPY, balances, rollup) | fmcg_a 21 s, fmcg_b 41 s, med_a 21 s, med_b 28 s |
| `make seed-reset` wall time (generate, reset, load, compact, reconcile) | 323 s on a quiet machine, 435 to 443 s when other work was running |
| Rows | 512 products, 164,297 bills, 324,446 sale lines, 345,850 movements, 10,663 batches, 2,528 purchase orders, 2,835 receipts, 2,205 returns, 4,986 count lines |
| Size | 359.0 MB tables and indexes. `inventory_movements` 110, `sale_lines` 85, `daily_product_stats` 59, `sales` 44, `synthetic_true_demand` 38 |
| Headroom for Prompt 4 | about 41 MB |
| Seed tests at scale 0.1 | 110 tests in 86 to 108 s |

### 16.2 How the simulation differs from the sketch in section 8

- **Owner ordering.** The owner reviews each supplier on its order weekdays (one or two a week). The reorder point is demand times (delivery time plus the wait for the next delivery day plus the review gap plus 2.5 days, or 3.8 days for most tenants, 4.6 for med_a), with lognormal noise (sd 0.25). The order up to level adds 8 or 9 days. The owner's idea of demand is recent sales plus half of the customers turned away, counted over days the product was on the shelf, never below 85 percent of the 56 day figure. The literal formula in section 8 (lead time plus 3 days) gave 15 percent stock-outs because of the weekly review gap.
- **Minimum order top up.** When an order is under the supplier minimum, fast movers are topped up one pack at a time, never past 40 days of cover. Without the cap one item piled up to 1,000 units.
- **Cash constraint.** fmcg_a funds the most urgent lines up to 70 percent of the value of the need.
- **Stock-out rate** (share of product days out all day) is 4.5 percent for fmcg_a (target 2 to 6), 2.6, 2.9 and 2.6 percent for the others (target 1 to 3). Bills per day are within 4 percent of the targets.
- **Returns** 0.9 percent of FMCG lines and 0.3 percent of medical lines, restock 80, damaged 15, expired 5. Voids 0.15 percent of bills, posted at the same time as the bill so the ledger replay never dips below zero.
- **Stock removed otherwise.** Damage 0.1 to 0.2 percent of cost of goods sold. Expiry write-offs are 0.06 and 0.13 percent for the FMCG tenants and 1.5 and 1.7 percent for the pharmacies, which have a history of short dated bulk deals (4 for med_a, 12 for med_b) that mostly expired. Supplier returns 20 percent of near-expiry batches where the supplier accepts them.
- **Counts** every 31 days (17 rounds). A class products are always in a round, other products 15 percent of the time, except the three S17 products in the last 50 days. About 12 percent of lines get a difference of -2 to +1.
- **Receipts** arrive at 06:30 to 06:50, counts are at 07:00, bills from 08:00, so a replay by time never goes negative. Unit costs follow the supplier term in force.
- **Dated FMCG goods** (biscuits, namkeen, dry fruits, packaged foods, dairy) are batch tracked, 26 to 35 products per FMCG tenant. All medicines with a shelf life are batch tracked.
- **Event curves** are described in `india-calendar.md` section 2.1. Two categories per FMCG tenant have no effect for some events (S02), and each pharmacy has one chance uplift of 1.35 for Diwali 2025 in one category (vitamins for med_a, hydration for med_b).

### 16.3 How the scenarios are planted

| Scenario | Mechanism |
|---|---|
| S03, S06 | A supply gap (blackout) for the product: deliveries in the window arrive empty, the product is not reordered, the shelf empties by itself. S06 starts about 120 days before the end and lasts past the end. At scale below 0.5 the stock left at the start is written off as damaged, otherwise the shelf would take months to empty |
| S04, S12, S13, S14 | Bulk purchases that arrive on a chosen day. Near-expiry ones get a short remaining shelf life and a quantity of about 2 times the demand until expiry, so about half is left. The planted expired batch of S12 is never written off |
| S05 | Demand drops to zero 85 to 110 days before the end while stock remains |
| S07 | The first order of a chosen supplier in the last 18 days never arrives. Its expected date is at least 6 days before the first plan date |
| S10 | Two products on a cash vendor with no delivery time at all, one product bought over the counter with no supplier term and no PO (exception receipts), one batch tracked product whose stock has no batch (movements and balances with a null batch) |
| S11 | Supplier price +9 percent on 12 Jan 2026 for edible oils (FMCG) or three chronic products from one maker (medical). The oils MRP follows +5 percent four weeks later |
| S15 | Launched 34 days before the end (`launched_on` set, 21 day ramp), first order 5 days before launch |
| S16 | Pack 48 (FMCG) or 100 (medical) with a minimum of two packs on slow products |
| S17 | Three A class products left out of every count in the last 50 days |
| S20 | Demand x1.5 from 190 days before the end, three other products get smaller steps |
| S08, S09 | `business_settings.weekly_budget` is 70 percent (fmcg_a) or 105 percent of the last 8 weeks of cost of goods sold plus 10 percent. Prompt 4 checked the ratio against the engine (P4.25, `D-082`): the final budgets are 55,000, 139,500, 42,000 and 114,000 rupees, which gives about 79 percent of need for fmcg_a and 111 to 125 percent for the others |

### 16.4 What is not in the seed yet

- The eight retrospective plans with synthetic decisions (section 12) need the engine, so they arrive in Prompt 4. The corpus types `decision_memory` and `report_narrative` follow them (P4.26).
- Embeddings (`seed.ingest_knowledge`) arrive in Prompt 7. Chunks are stored with `embedding = NULL`: 117 chunks, of which 25 are global app knowledge.
- The daily rollup now runs through the rollup service (`services/rollup.py`, formerly the SQL fallback `seed/rollup_sql.py`) with the same rules as `engine-spec.md` section 3. P4.24 replaces it.
- Tax rates use one mapping for the whole history, so sales before 22 Sep 2025 carry the new slab (representative data, not tax advice).
