# UI screens

Screen by screen specification. Follow `ui-design-system.md` for every visual decision and `ui-copywriting.md` for every string. Strings go in `src/copy/en.ts`.

General behaviour for every screen:
- Filters, sort, page and selected tab live in the URL query string, so views can be shared and the assistant can set them.
- Every list has loading (skeleton in the table frame), empty (sentence plus action) and error (banner with Retry) states.
- Data freshness line where relevant: "Data up to 11 Oct 2026".
- Every chart and KPI block has an Explain button (opens the Assistant panel with that element as context).
- Money and quantity formats per design system section 8.
- Keyboard: `Ctrl or Cmd + K` command palette, `/` focuses the screen search field, `Esc` closes dialogs and drawers.

Routes:

| Route | Screen |
|---|---|
| `/login` | Sign in |
| `/` | Overview |
| `/plan` and `/plan/:reportId` | Monday plan |
| `/products`, `/products/:id` | Products |
| `/sales`, `/sales/new`, `/sales/:id` | Sales |
| `/purchases`, `/purchases/new`, `/purchases/:id` | Purchases |
| `/stock` | Stock (tabs by `?tab=`) |
| `/insights` | Insights (tabs by `?tab=`) |
| `/settings` | Settings (tabs by `?tab=`) |
| `/assistant` | Assistant full page |
| `/_ui` | Component gallery (dev only) |

---

## 1. Sign in (`/login`)

Layout: a single column, left aligned block 360 px wide, vertically near the top third of the page on `--color-bg`. No hero, no illustration.
Content, top to bottom:
- Product name "Backroom" in `text-xl` 600, one line under it in `text-2`: "Sign in to your business."
- Email field, password field with a "Show" text toggle, button "Sign in" (primary, full width of the block).
- Error text under the form: "Email or password is not right." or the lockout message.
- If `DEMO_LOGIN_ENABLED`: a divider "Or look around with demo data" and four plain text buttons, one per business (secondary): "Shree Sai Kirana and General Stores", "Mahalaxmi Super Mart", "Sanjivani Medical and General", "Aarogya Care Pharmacy". Clicking calls demo login.
- Footer line in `text-xs` `text-3`: "Demo data is simulated."
States: pending sign in shows spinner in the button. If the request takes more than 3 seconds, show under the button: "The server is waking up. This can take up to a minute." The page pings `/health` on load.
On success go to the last visited route or `/`.

## 2. Overview (`/`)

Header: "Overview", context "Data up to 11 Oct 2026".
1. **Needs attention** (panel at top, most important): up to 8 rows. Each row: icon-free, a risk word and dot, a sentence, and a link. Sources: critical lines ("Biscuits 100 g will run out on 14 Oct, before the next delivery"), batches expiring within 14 days, overdue orders, data errors, a plan waiting for decisions. Empty: "Nothing needs attention right now."
2. **KPI strip** (one panel, five blocks separated by rules): Stock value, Suggested spend this week (with "Budget ₹2,00,000" hint), Lines likely to run out (count of critical and high), Stock not moving (value), Stock near expiry (value and count of batches). Each links to the relevant screen.
3. **Sales, last 12 weeks** (line chart, 220 px, festival bands labelled). Explain button.
4. **Days of stock by category** (horizontal bars, sorted ascending so thin cover is at the top, a vertical rule at the review period). Explain button.
5. **This week's plan** panel: status ("Ready, 41 lines to buy", "Waiting for your decisions: 12 of 41"), the three largest critical lines, button "Open Monday plan".
6. **Recent activity**: last 8 audit style events in plain words ("Bill B2610-00412 saved", "Goods received from Supplier X").
Layout: needs attention and KPI strip full width, then a two column grid (chart | cover chart), then plan panel and recent activity side by side.
Filters: none. `apply_filters` not applicable.

## 3. Monday plan (`/plan`)

The main screen. Header: "Monday plan", context "Week of 12 Oct 2026. Data up to 11 Oct 2026." Right side: status chip (Ready, Creating, Failed), week switcher (previous and next week buttons and a select of past weeks), **Download** menu button (PDF, Excel, CSV purchase list, CSV all lines), **Create purchase orders** (primary, enabled when at least one line is approved or edited), overflow menu: Regenerate plan.

If no report: empty state with "Create plan now" button. While creating: progress banner "Creating the plan. This takes about a minute." and polling every 3 s.

**Summary block** (one panel): big number "Planned spend ₹1,82,340" in `text-display`, beside it a thin budget bar with the budget and remaining or shortfall in words ("₹17,660 left in budget" or "₹46,000 short of what is needed"). Then a row of six small figures: Lines to buy, Chance of running out (critical and high count), Stock not moving (value), Stock that may expire (value), Data warnings, Forecast confidence mix (text "High 52, Fair 30, Low 10"). Festival note line if an event is within 21 days: "Diwali starts on 6 Nov. Dry fruits and Puja items are forecast higher." (link to Festival tab).
Below: if the Monday Analyst produced notes, a collapsed panel "Notes on this plan" with 4 to 7 short notes.

**Tabs** with counts: Buy (41), Do not buy (58), Watch closely (9), Reduce exposure (12), Festival and season, Budget, Data notes.

### Buy tab
Toolbar: search, filters (Supplier, Category, Risk, Forecast confidence, Decision: All, Pending, Approved, Edited, Rejected), "Group by supplier" switch, bulk actions appear on selection: "Approve selected", "Reject selected". Select all checkbox.
Table columns: select, expand chevron, Product (name, SKU in mono, category small), Supplier, Forecast for days to cover, Sellable stock, Incoming, Buffer stock, Shortfall, Pack of, Suggested (units, with "= 2 packs" under), Funded (units, bold when it differs from suggested), Spend, Chance of running out (risk word), Forecast confidence, Decision (status chip), actions (Approve, Edit, Reject as text buttons, overflow for "Ask assistant", "Open product").
Row expand shows two columns:
- Left: **How we got here**: key value list with provenance tags: Days to cover (lead time source), Forecast per day, Forecast for days to cover, Sellable stock, Expected to expire unsold, Incoming confirmed, Incoming ignored (late order), Reserved, Stock you can count on, Buffer stock (and the service level used), Target stock, Shortfall, Minimum order, Pack of, Suggested, Funded, Extra from pack rounding, Unit cost, Spend.
- Right: **Why**: reason text (full sentence), warnings (each a line with a small icon-free marker), a small line chart of the last 8 weeks sales with the next 4 weeks forecast and its range, buttons "Ask assistant about this line" and "Investigate" (runs the exception investigator).
Edit: opens a popover or dialog with the **pack stepper** and live "Spend ₹X, budget left ₹Y", a reason select (Shelf space, Supplier issue, Cash is tight, Already ordered, Demand will change, Other) and optional text. Save creates an `edited` decision. Reject asks for a reason the same way. Approve saves immediately.
Sticky footer bar: "Approved ₹1,24,000 of ₹2,00,000 budget. 28 lines pending." with the Create purchase orders button repeated.
`apply_filters` keys: `q, supplier_id, category_id, risk, confidence, decision, group_by_supplier`.

### Do not buy tab
Columns: Product, Days of cover, Sellable stock, Incoming, Forecast for days to cover, Why not (reason text short). Filters: search, category, supplier.

### Watch closely tab
Intro line: "These may run out before the next delivery or have orders running late." Columns: Product, Runs out on (date), Next delivery (date), Chance of running out, Late orders, Forecast confidence, What you can do (text, for example "Ask the supplier for an earlier delivery", "Move stock from another shelf"). Buttons per row: Investigate, Ask assistant.

### Reduce exposure tab
Sub sections as segmented control: Not selling, Selling slowly, Check first, Extra stock, May expire. Each a table:
- Not selling: product, last sale date, stock, value, status note.
- Check first: product, why we are not sure ("Out of stock for 45 of the last 60 days"), stock.
- May expire: **batch table**: product, batch no (mono), expiry date, days left, quantity, expected unsold, value at cost, supplier return option (from supplier policy: "Supplier takes returns until 14 Dec"), button "Write off" (only for expired). Sorted by earliest expiry. For the medical tenants this is the Expiry view with FEFO order.
Totals row with value at cost.

### Festival and season tab
Header sentence explaining dates may shift by a day for unverified events. List of events within 35 days (or the next one): a panel per event with name, dates, days away, delivery delay padding, a table of categories: category, effect on forecast (for example "up 62%"), label (Learned from last year, Set by you, Not enough evidence), occurrences used, products affected, evidence numbers (expandable). Medical tenants see seasons (monsoon, summer, winter) and a note that festivals do not raise medicine forecasts unless the data shows it. Owner can click "Set my own change" to enter a configured multiplier for a category (dialog with the percent, warning "This is your estimate, not learned from sales").

### Budget tab
Budget input summary (links to Settings), a horizontal bar: funded, unfunded needed, budget line. Table of **unfunded lines** (ranked by priority score) with the quantity not funded and its spend. Table **Still at risk after funding**. A short explanation of how lines are ranked with the four weights (read from settings) in plain words. Never says everything is covered when not: heading "Not covered: 12 lines, ₹46,000" or "Everything suggested fits the budget."

### Data notes tab
Table of issues relevant to this plan: severity, what, how many products, what to do (link to the product or settings), and a button "Ask assistant to explain". Also the assumptions in use (default delivery time, products with unrecorded stockouts, calendar not verified).

Decision persistence: optimistic update, then confirm. A decision on an old report is allowed but shows a banner "This is an older plan."

## 4. Products (`/products`)

List: search (name, SKU, brand, generic), filters (Category, Supplier, Status: Active, Not selling, Selling slowly, New, Inactive; Batch tracked), table columns: Product (name, SKU mono), Category, Unit and pack, Selling price, Stock, Days of cover, Plan status (chip: Buy, Watch, OK, Not selling), Supplier. Row click opens `/products/:id`. Buttons: "Add product". `apply_filters` keys: `q, category_id, supplier_id, status, batch_tracked`.

Add and edit product: a page with sections Basic (name, SKU, brand, category, unit, pack label, barcode), Price and tax (MRP, selling price, GST rate), Stock rules (batch tracked, shelf life days, minimum display stock, seasonal, launch date), Medicine details (only for medical tenants: generic name, strength, form, manufacturer, schedule class flag labelled "Schedule (for your records)"), Supplier terms (primary supplier, purchase price, pack of, minimum order, delivery time), Notes. Validation inline.

Product detail (`/products/:id`): header with name, SKU, category, status chips, and key numbers (stock, days of cover, last sale, price). Tabs: **Overview** (editable details), **Stock and batches** (batch table with expiry, FEFO order, quantity, value, write off), **Sales** (chart of daily sales for 90 days with stockout shading, promotion and festival markers, and a table of recent bills), **Purchases** (orders and receipts, supplier price over time), **Plan history** (past recommendations, decisions, reasons, forecast versus actual chart), **Forecast** (next 28 days with range, method, past accuracy numbers: forecast error, forecast tendency, confidence explanation), **Activity** (audit and movements). Buttons: Edit, Record adjustment, Deactivate, "Ask assistant".

## 5. Sales

`/sales` list: date range (default last 7 days), search by bill number, status filter (Completed, Void), summary strip (Bills, Sales, Returns for the range), table: Bill, Date and time, Items, Payment, Total, Status. Button "New bill".

`/sales/new` (fast entry, designed for speed):
- Product search field focused on load (name, SKU, barcode, generic), results list with stock shown, Enter adds the first match. Barcode scanners type and press Enter, which works.
- Lines table: Product, Batch (auto FEFO for tracked products, shown with expiry, changeable), Quantity (default 1), Price (default selling price, editable), Discount, Line total, remove. Stock warning inline ("Only 4 left").
- Right panel (or bottom on mobile): total, payment mode (Cash, UPI, Card, Credit as a segmented control), "Save bill" (primary). `Ctrl+Enter` saves.
- After save: toast "Bill saved." and the form clears with focus back on search. Possible duplicate shows a banner "A bill with the same items and total was saved a minute ago. Save anyway?" with Save anyway and Cancel.
- Idempotency key generated when the form opens and kept until saved.

`/sales/:id` bill detail: lines, totals, returns made, actions: "Record return" (dialog: pick lines, quantities, reason, what to do with the stock: Put back on shelf, Damaged, Expired), "Void bill" (confirm dialog with reason).

## 6. Purchases

`/purchases` list: filters (Status, Supplier, Overdue only), table: Order no, Supplier, Date, Expected on, Status chip, Lines, Value, Received so far. Overdue rows show "6 days late" in high colour. Button "New order".

`/purchases/new`: choose supplier (shows delivery days and minimum order value), add lines by product search (cost, pack and minimum order prefill from terms, shows suggested quantity from the current plan if any), expected date (default from delivery time and supplier delivery days, shown with its source), notes. Save as draft, or "Save and mark as sent".

`/purchases/:id`: header with status, timeline (Created, Sent, Received in part, Received), lines table (ordered, received, open), actions by state: Send, Cancel, Close, **Receive goods** (opens receipt form).
Receipt form: received date, invoice number and total (optional), lines with quantity received (default open quantity), unit cost (default order cost, warns when it changes by more than 10 percent), and for batch tracked products batch number and expiry date and MRP (required, with expiry format hint). Exception toggle appears automatically when a quantity exceeds open quantity or no order exists: requires a note. Result toast "Goods received."

## 7. Stock (`/stock`)

Tabs: **Levels**, **Batches and expiry**, **Movements**, **Counts**, **Out of stock history**.

- **Levels**: search, category, status filters, columns: Product, On hand, Sellable, Incoming, Days of cover, Value at cost, Status chip, Last count date. Buttons: "Record adjustment", "Start stock count". `apply_filters` keys: `q, category_id, status, risk`.
- **Batches and expiry**: window control (Expired, 30, 60, 90 days, All), product search, table sorted by earliest expiry: Product, Batch no, Expiry, Days left (colour by window), Quantity, Value, "Sell first" marker for the earliest batch per product (FEFO), supplier return option, action "Write off" for expired. Totals. Medical tenants default to this tab view for expiry.
- **Movements**: filters (Product, Type, Date range), table: Date and time, Product, Batch, Type (plain labels: Sale, Delivery, Return, Damage, Expired, Adjustment, Count correction, Opening), Change (plus or minus), Reason, By. Read only.
- **Counts**: list of counts, "Start count" (choose all or a category or a selection), count sheet table (Product, Batch, In system, Counted input, Difference), "Save draft", "Post count" with a confirm dialog showing the total difference and value.
- **Out of stock history**: recorded intervals table (Product, From, To, Source: You recorded, Worked out from stock history), "Add interval" dialog. Explanation sentence: "Recording days you ran out helps forecasts, because sales on those days understate demand."

Adjustment dialog: product (search), batch (if tracked), change (plus or minus quantity), reason (Damage, Expired, Lost or stolen, Found, Correction, Returned to supplier, Other), note (required for Other).

## 8. Insights (`/insights`)

Tabs: **Sales and trends**, **Movers**, **Forecast accuracy**, **Festival effects**, **Suppliers**, **Expiry and waste**.
- **Sales and trends**: date range, group by day or week, sales and units lines, category breakdown bars, festival bands, weekday pattern bars, month start pattern note.
- **Movers**: ABC table by revenue share, plus lists of Fast (top 15), Selling slowly, Not selling with value, and "Check first".
- **Forecast accuracy**: summary numbers (Forecast error for the business, Forecast tendency, versus a simple baseline), table by category and demand type (Steady, Variable, Occasional, Lumpy shown as plain words) with Average miss, Forecast error (or "Not meaningful" for occasional items), Tendency, method used, number of products. Chart: forecast versus actual for a selected product or category over 12 weeks. Note under the table about stock-limited days and how they were handled.
- **Festival effects**: per event list of learned effects with evidence and label, the history of the event in sales (chart with band), what was applied in this week's plan.
- **Suppliers**: scorecards table: Supplier, Orders, Late deliveries (%), Average delay (days), Delivered in full (%), Price change in last 6 months, Minimum order, returns policy. Row opens a drawer with the policy text snippets (from RAG documents) and recent orders.
- **Expiry and waste**: write-offs by month and reason (bars), value lost, current exposure, suppliers that accept returns.
`apply_filters` keys per tab: `from, to, group, category_id, event_key, supplier_id`.

## 9. Settings (`/settings`)

Tabs: **Business**, **Planning**, **Festival calendar**, **Account**, **About**.
- **Business**: name (read only for now), timezone (read only), currency, demo data note.
- **Planning**: weekly budget (optional, with "No limit" checkbox), service level (select: 90, 95, 97, 99 percent with the plain text "Higher means more buffer stock and more cash tied up"), review period (days), default delivery time (days), near-expiry window (days), not-selling period (days), slow cover days, extra stock horizon, stale count days, share of shelf life we plan to hold (percent), pack rounding (Round up, Round to nearest safe pack), priority weights (four sliders summing to 100 with plain labels: Chance of running out, Profit, Forecast confidence, Extra stock), "Use assistant" switch. Save button with a diff confirm. Changes apply from the next plan.
- **Festival calendar**: table of events (name, dates, verified or "Dates may shift", before and after days, delivery delay days), add event dialog, edit unverified events, per category "Set my own change" entries list.
- **Account**: change password form (current, new, confirm, rules text), "Sign out everywhere" button.
- **About**: version, data cutoff of latest plan, model version, demo data statement, limitations in plain words (what the plan can and cannot do, not tax or compliance advice, medicines: stock and buying only).

For synthetic tenants only and when allowed: a "Demo tools" section with "Simulate next week" and "Reset demo data" (confirm dialog), hidden in production unless enabled.

## 10. Assistant (`/assistant` and docked panel)

Full page layout: left column thread list (search, new chat), right the conversation, same components as the panel. Panel and page share state. Starter prompts: "What should I buy this week?", "What might run out before delivery?", "What is about to expire?", "Why is this line high risk?" (only when a line is selected), "What if my budget is ₹1,50,000?", "Explain the Diwali change in the forecast".
Entry points (Explain buttons): KPI blocks, charts, plan lines ("Ask assistant"), data notes, expiry rows. Each opens the panel with `page_context.selected` set and a prefilled message the person can edit before sending.
Login nudge: after sign in, if `GET /chat/nudges` has content show it once as a small panel at the top of Overview titled "Today", 3 to 5 plain lines, dismiss with "Got it".
Action cards confirm through `POST /agent-actions/{id}/confirm`; success updates the relevant screen's queries.
UI actions from the assistant: `navigate`, `apply_filters` (only the keys listed per screen above), `open_product`, `open_report_line`, `start_tour`. Anything else is ignored and logged.
**Guided tour** (`plan_overview`): five steps highlighting Summary, Buy, Watch, Reduce exposure, Budget, each with a one sentence explanation generated from stored numbers, Next and Back buttons, Escape ends it.

## 11. Global components behaviour

- **Command palette**: pages and products. Selecting a product opens its page.
- **Session expiry**: a 401 triggers one silent refresh, else a dialog "You were signed out. Sign in to continue." that keeps the current route.
- **Offline or server down**: persistent banner "We cannot reach the server" with Retry. The sale form keeps its content.
- **Cold start**: first request failing with a timeout shows the "server is waking up" banner and retries automatically up to 3 times.
- **Not found**: "We could not find that page." with a link to Overview.

## 12. Acceptance for UI work

For every screen: matches this file, uses tokens only, has loading, empty and error states, keyboard reachable, passes the anti-template checklist, strings pass `check_copy`, no hex colours in components, screenshot reviewed at 1440 and 390 px widths.
