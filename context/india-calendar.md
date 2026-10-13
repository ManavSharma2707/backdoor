# India calendar specification

Seeds `calendar_events` and drives festival and season logic. Region: Maharashtra flavour, but no location is shown in the product.

Lunar festival dates move every year and some are decided by moon sighting. Several sources disagree by one day. Treat every date here as a **best known value**, store `is_verified = false` until confirmed, and show a small "dates may shift by a day" note on the Festival insights screen for unverified events.

Verification step (Prompt 3, one time): for every row marked `verify`, check two independent official or panchang sources, correct the row, set `is_verified = true`, and log the change in `memory.md`. State sources in `source_note`. Searches done on 13 Oct 2026 confirmed: Ganesh Chaturthi 14 Sep 2026 (Anant Chaturdashi 25 Sep), Diwali Lakshmi Puja Sunday 8 Nov 2026 with Dhanteras 6 Nov and Bhai Dooj about 10 Nov, Dussehra 20 Oct 2026 (one Maharashtra list says 21 Oct), Raksha Bandhan 28 Aug 2026, Holi 3 Mar 2026, Gudi Padwa 19 Mar 2026 (a state list says 20 Mar), Eid al-Fitr 21 Mar 2026, Bakri Eid 27 or 28 May 2026.

---

## 1. Events

Columns: `event_key`, start, end, pre window days, post window days, supplier delay days, kind, status.

### 2025 (inside simulated history from 14 Apr 2025)

| event_key | Name | Start | End | Pre | Post | Delay | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `eid_adha` | Bakri Eid | 2025-06-07 | 2025-06-07 | 3 | 1 | 0 | festival | verify |
| `monsoon` | Monsoon | 2025-06-10 | 2025-09-30 | 0 | 0 | 0 | season | seasonal |
| `raksha_bandhan` | Raksha Bandhan | 2025-08-09 | 2025-08-09 | 7 | 2 | 0 | festival | verify |
| `ganesh_chaturthi` | Ganesh Chaturthi | 2025-08-27 | 2025-09-06 | 10 | 3 | 1 | festival | verify |
| `navratri_dussehra` | Navratri and Dussehra | 2025-09-22 | 2025-10-02 | 5 | 2 | 1 | festival | verify |
| `diwali` | Diwali | 2025-10-18 | 2025-10-23 | 14 | 4 | 2 | festival | verify |
| `winter` | Winter | 2025-11-15 | 2026-02-15 | 0 | 0 | 0 | season | seasonal |
| `christmas_ny` | Christmas and New Year | 2025-12-24 | 2026-01-01 | 7 | 2 | 0 | festival | verify |

### 2026

| event_key | Name | Start | End | Pre | Post | Delay | Kind | Status |
|---|---|---|---|---|---|---|---|---|
| `makar_sankranti` | Makar Sankranti | 2026-01-14 | 2026-01-14 | 5 | 1 | 0 | festival | verify |
| `holi` | Holi | 2026-03-03 | 2026-03-03 | 5 | 2 | 0 | festival | verify |
| `gudi_padwa` | Gudi Padwa | 2026-03-19 | 2026-03-19 | 5 | 2 | 0 | festival | verify |
| `eid_fitr` | Eid al-Fitr | 2026-03-21 | 2026-03-21 | 7 | 2 | 0 | festival | verify |
| `summer` | Summer | 2026-03-01 | 2026-05-31 | 0 | 0 | 0 | season | seasonal |
| `eid_adha` | Bakri Eid | 2026-05-28 | 2026-05-28 | 3 | 1 | 0 | festival | verify |
| `monsoon` | Monsoon | 2026-06-10 | 2026-09-30 | 0 | 0 | 0 | season | seasonal |
| `raksha_bandhan` | Raksha Bandhan | 2026-08-28 | 2026-08-28 | 7 | 2 | 0 | festival | confirmed by search, re-check |
| `ganesh_chaturthi` | Ganesh Chaturthi | 2026-09-14 | 2026-09-25 | 10 | 3 | 1 | festival | confirmed by search, re-check |
| `navratri_dussehra` | Navratri and Dussehra | 2026-10-11 | 2026-10-20 | 5 | 2 | 1 | festival | verify start, Dussehra 20 Oct |
| `diwali` | Diwali | 2026-11-06 | 2026-11-10 | 14 | 4 | 2 | festival | confirmed by search, re-check |
| `winter` | Winter | 2026-11-15 | 2027-02-15 | 0 | 0 | 0 | season | seasonal |
| `christmas_ny` | Christmas and New Year | 2026-12-24 | 2027-01-01 | 7 | 2 | 0 | festival | verify |

The 2025 season rows `summer` for 2025 (1 Mar to 31 May 2025) exist for completeness but mostly fall before the history starts.

### 2027 (approximate, for forecasts beyond 2026, always unverified)

| event_key | Start | End | Note |
|---|---|---|---|
| `makar_sankranti` | 2027-01-14 | 2027-01-14 | |
| `eid_fitr` | 2027-03-10 | 2027-03-10 | moon dependent |
| `holi` | 2027-03-22 | 2027-03-22 | |
| `gudi_padwa` | 2027-04-07 | 2027-04-07 | |
| `ganesh_chaturthi` | 2027-09-04 | 2027-09-14 | |
| `diwali` | 2027-10-29 | 2027-11-02 | |

Each occurrence is a row with slug `{event_key}-{year}`. `UQ (event_key, start_date)`.

## 2. Windows

- `pre` window days: ramp-up period of stocking and shopping. Diwali and Ganesh Chaturthi have the longest.
- `post` window days: hangover dip.
- `delivery_delay_days`: how many extra days supplier deliveries are expected to take during the pre and during window (traffic, labour, holidays). Added to lead time when `apply_festival_lead_padding` is on.
- `affects_hours`: true for Diwali Lakshmi Puja day and Holi afternoon (reduced trading hours). Informational, shown as a note on the Festival tab.

## 3. Category tags (what each event touches)

Used by the seed generator (true effects, see `seed-data-spec.md`), by the UI to explain, and to suggest candidate categories to the owner for manual effects. The engine never uses these tags to apply an uplift. It only applies learned or owner configured effects.

| event_key | FMCG categories | Medical |
|---|---|---|
| `diwali` | Dry fruits, Chocolates and sweets, Namkeen and snacks, Home care, Festival and puja items, Edible oils and ghee, Sugar | None. Hours and delivery timing only |
| `ganesh_chaturthi` | Festival and puja items, Dry fruits, Sugar, Atta | None |
| `navratri_dussehra` | Festival and puja items, Dry fruits and sweets | None |
| `raksha_bandhan` | Chocolates and sweets, Dry fruits | None |
| `gudi_padwa` | Sugar, Festival items, sweets | None |
| `holi` | Beverages, sweets, snacks | None |
| `eid_fitr`, `eid_adha` | Dry fruits, sugar, dairy | None |
| `christmas_ny` | Chocolates, beverages, snacks | None |
| `makar_sankranti` | Sugar and jaggery, sweets, dry fruits | None |
| `monsoon` | Tea, biscuits, namkeen, noodles, beverages (down) | Analgesics and antipyretics, GI, respiratory, dermatology (fungal), antibiotics |
| `summer` | Beverages, water, ice related | ORS and electrolytes, hydration, sunscreen related, GI |
| `winter` | Dry fruits, ghee, jaggery, tea | Respiratory, vitamins, topical pain, dry skin dermatology |

## 4. Other India specific patterns

| Pattern | Where | Detail |
|---|---|---|
| Monthly ration shopping | FMCG staples | Days 1 to 7 of the month: 1.5 to 2.0 times demand for atta, rice, dal, oil, sugar. Learned by weekday and month-day features in LightGBM, and shown in insights |
| Chronic refill cycle | Medical | Days 1 to 10 of the month, 1.4 times for chronic categories |
| Salary week | FMCG discretionary | Days 1 to 7 a modest lift for snacks, personal care |
| Weekend peak | FMCG snacks, beverages, biscuits | Saturday and Sunday |
| Wedding season | Not modelled in MVP | Mention as future |
| Local holidays | All | Muhurat trading day and similar are not modelled |

## 5. Implementation notes

- `calendar_events` is seeded by a migration data step or by `seed.run --reference` (idempotent upsert by slug), so every tenant, including newly registered ones, sees the same events.
- Owner edits create rows with `is_verified = false` and `source_note = 'owner'`.
- CALENDAR_STALE DQ check: no event with `end_date >= today` and `start_date <= today + 60`.
- Every date shown in the UI uses `DD MMM YYYY` (`12 Oct 2026`). Festival names use common English spellings used in Maharashtra, no transliteration marks.
- When the owner opens a festival, the UI states what the numbers are based on (for example "Learned from Diwali 2025, one occurrence") and never presents an estimated uplift as certain.
