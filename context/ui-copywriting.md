# UI copywriting

All text a person reads in the product: labels, buttons, errors, empty states, toasts, emails (none yet), PDF and Excel text, seed corpus text, assistant output. It must sound like a clear, helpful colleague at a shop, not like a brochure and not like a machine.

All UI strings live in `frontend/src/copy/en.ts`, grouped by screen. Backend error messages and report reason templates follow the same rules and live in `backend/app/core/messages.py` and `engine/report_builder.py`.

---

## 1. Voice

- Plain, direct, calm. Short sentences. Say what happened, say what to do next.
- Indian English for words where it matters: "stock", "bill", "lakh", "kirana" is not used in UI. Use "Rupees" in words only if needed, the symbol `₹` in numbers. Spelling: Indian English follows British forms for "colour", "organise", "cheque", "licence" (noun). Keep these consistent. Use "program" for software.
- Talk to the person as "you". The product says "we" sparingly ("We could not save this bill."). Never "I" except in the assistant, which may use "I".
- Respect time and attention. No cheerleading. No apologies unless something actually went wrong because of us.
- Numbers as digits. Units after the number ("20 packs").
- Use the words shop owners use: stock, bill, return, supplier, order, delivery, expiry, shelf.

## 2. Hard rules

1. **No em dashes and no en dashes anywhere** (the long dash characters, U+2014 and U+2013). Use a comma, colon, full stop, or the word "to" for ranges ("12 to 18 months"). Hyphens only inside compound words (`non-moving`, `pre-festival`) and negative numbers use a minus sign.
2. No exclamation marks. No emoji. No ellipsis character used for effect (a loading label may end with three full stops: "Saving...").
3. Sentence case for everything: buttons, headings, tabs, column headers. Only proper nouns capitalised (Diwali, GST).
4. No semicolons. No parentheses for asides in buttons and headings.
5. No rhetorical questions, no "not just X but Y", no "whether you are A or B", no lists of exactly three adjectives, no triplets for rhythm.
6. Do not describe the product. Describe the action or the situation.
7. Never blame the person. "Quantity must be more than zero." not "You entered an invalid quantity."
8. Errors say what to do. Success messages say what happened, once, briefly.
9. Do not use the words in the banned list.
10. Lengths: button labels 1 to 3 words, toasts under 80 characters, empty states 2 short sentences, helper text one sentence.

## 3. Banned words and phrases

seamless, seamlessly, robust, powerful, leverage, utilise (use "use"), unlock, supercharge, elevate, empower, effortless, effortlessly, streamline, cutting-edge, state-of-the-art, game-changer, revolutionary, intelligent (as marketing), smart (as marketing, "smart insights"), AI-powered, magic, magical, delve, dive in, journey, ecosystem, holistic, synergy, "at your fingertips", "in today's", "it's important to note", "welcome back", "let's get started", "oops", "uh oh", "hang tight", "sit back and relax", "simply", "just" (as minimiser), "easily", "insights" (use "numbers" or "trends"), "actionable", "best-in-class", "next-level".

`check_copy.py` fails the build on: em dash, en dash, exclamation mark in `copy/en.ts` strings, emoji, and any banned word in `en.ts`, `messages.py`, corpus text, report templates.

## 4. Term mapping (technical term to UI wording)

| Technical | UI label | Short explanation (tooltip) |
|---|---|---|
| Safety stock | Buffer stock | Extra stock kept in case sales run higher than expected |
| Protection period | Days to cover | Days between now and when the next order can arrive |
| Lead time | Delivery time | Days a supplier takes to deliver after you order |
| Inventory position | Stock you can count on | Sellable stock plus confirmed deliveries, minus reserved stock |
| Usable stock | Sellable stock | Stock that is in date and fit to sell |
| MOQ | Minimum order | Smallest quantity the supplier accepts |
| Pack size | Pack of | Quantity in one supplier pack |
| Raw requirement | Shortfall | How much you are short before pack rounding |
| Stockout | Out of stock | |
| Stockout risk | Chance of running out | |
| Dead stock | Stock not moving | No sales for a long time |
| Non-moving | Not selling | |
| Slow-moving | Selling slowly | |
| Excess stock | Extra stock | More than expected sales need |
| FEFO | Sell earliest expiry first | |
| Expiry exposure | Stock that may expire | Quantity likely to expire before it sells |
| WAPE | Forecast error | Share of sales the forecast missed on average |
| Bias | Forecast tendency | Whether forecasts run high or low |
| MAE | Average miss | Average units the forecast was off by |
| Confidence (high, medium, low) | Forecast confidence: High, Fair, Low | |
| Censored demand | Sales limited by stock | Days when you ran out, so sales understate demand |
| Provenance: observed, calculated, assumed | Recorded, Worked out, Assumed | |
| Recommendation run | Plan | |
| Backtest | Past accuracy check | |
| Synthetic | Demo data | |
| Data cutoff | Data up to | |
| Idempotency, ledger, movement | Never shown. Say "stock history" for the ledger | |

## 5. Patterns

### Buttons and actions
Verb first: "Save bill", "Add product", "Record return", "Receive goods", "Approve", "Edit quantity", "Reject", "Create purchase orders", "Download Excel", "Download PDF", "Download CSV", "Regenerate plan", "Sign in", "Sign out", "Change password". Confirm buttons repeat the action ("Void bill", not "OK"). Cancel is "Cancel" or "Not now".

### Empty states (what is missing, then what to do)
- Sales: "No bills yet for these dates. Change the dates or add a bill."
- Monday plan, none yet: "There is no plan for this week yet. It is created every Monday at 6 am. You can also create it now."
- Stock, expiry filter empty: "Nothing expires in the next 60 days."
- Assistant, first open: starter prompts only.

### Loading
Skeleton blocks. Text only for long jobs: "Creating the plan. This takes about a minute." Cold start: "The server is waking up. This can take up to a minute."

### Errors (what happened, what to do)
- Network: "We could not reach the server. Check your connection and try again."
- Session ended: "You were signed out. Sign in to continue."
- Credentials: "Email or password is not right."
- Locked: "Too many attempts. Try again in 15 minutes."
- Validation: "Quantity must be more than zero." "Enter a date on or after 12 Oct 2026." "Pick a supplier."
- Stock: "Only 4 packs of Biscuits 100 g are in stock. Lower the quantity or record a delivery first."
- Receipt too large: "You can receive up to 20 packs against this order. Mark it as an exception to receive more."
- Server: "Something went wrong on our side. Try again. If it keeps happening, tell us the time it happened."
- Quota (assistant): "The assistant is busy right now. Try again in a minute. You can still read the reason on each line."

### Success toasts
"Bill saved." "Return recorded." "Goods received." "Order created." "Plan created." "Saved." "Decision saved." "12 lines approved." "Purchase orders created for 4 suppliers."

### Confirm dialogs
Title says the action and object. Body says the consequence. Examples:
- "Void this bill?" "The stock is added back and the bill no longer counts in sales. This cannot be undone."
- "Regenerate the plan?" "This creates a new version with today's data. Your decisions on the current plan stay on that version."
- "Reject 6 lines?" "Pick a reason so the plan can learn from it." (Reason list: Shelf space, Supplier issue, Cash is tight, Already ordered, Demand will change, Other.)

### Help text and tooltips
One sentence, no jargon, no trailing flourish. "Packs the supplier sells in. We round your order up to a whole pack."

### Provenance and notes
Tags: "Recorded", "Worked out", "Assumed". Notes: "Delivery time is assumed to be 3 days because none is set for this supplier."

### Festival text
"Diwali starts on 6 Nov. Last year Dry fruits sold about 2.2 times the usual in the weeks before. We have raised the forecast by that amount." For no evidence: "We do not have enough past sales to adjust for Navratri on Namkeen. The forecast uses normal sales."

### Plan reason examples (from templates)
"Demand for the next 10 days is about 30 packs. You have 12 on the shelf and 5 on the way, and we keep 4 as buffer, so you are short by 17. The supplier sells in packs of 10, so we suggest 20."
"This will run out on 14 Oct, two days before the next delivery. Ordering now cannot fix that, but it covers the days after."
"Some stock expires on 20 Nov and may not sell in time, so we count 9 fewer units as usable."

### Assistant voice
First sentence is the answer. Then the support in a few plain sentences. Say "I" sparingly. If it does not have a number it says so: "I could not find the lead time for this supplier." Never "As an AI". Never apologise twice. Cites sources through chips, not in prose. Medicines: "I can help with stock and buying for medicines, not with advice on how to use them. A pharmacist or doctor is the right person for that."

## 6. Formats (single source: `lib/format.ts` and `app/core/format.py`)

| Item | Format |
|---|---|
| Money | `₹1,82,340` and `₹1,82,340.50`, compact `₹1.8 lakh`, `₹1.2 crore` |
| Quantity | `1,250` and `12.5 kg` |
| Date | `12 Oct 2026` |
| Date range | `12 to 18 Oct 2026` |
| Week | `Week of 12 Oct` |
| Time | `6:02 am` |
| Percent | `31%` |
| Relative | `in 3 days (16 Oct)` |
| Ids | SKU and batch in Plex Mono |

## 7. Humanizer checklist (run on every new string before committing)

- Read it aloud. Would a person at the shop say it?
- Remove the first word if it is filler ("Please note", "Simply", "Just", "Here you can").
- Is there a dash? Replace it.
- Can it be said in fewer words? Cut.
- Does it repeat the heading? Cut.
- Does it sound like a template (three parallel clauses, a tidy summary sentence at the end)? Rewrite with uneven, natural rhythm.
- Does it name the thing and the action precisely?
- Is any claim bigger than the data? Soften with what the data shows ("based on last year").

## 8. Enforcement

- `scripts/check_copy.py` scans: `frontend/src/**/*.{ts,tsx}` (string literals and JSX text), `backend/app/**/*.py` message modules and templates, `backend/seed/corpus/**`. It also scans `context/**` and `CLAUDE.md`, but only for the two dash characters (these docs legitimately list banned words). Fails on dashes, banned words, emoji, exclamation marks in user-facing strings. It ignores code comments and URLs. Run in pre-commit hook configuration, `make check-copy` and CI.
- `app/core/text.py::humanize_text()` is applied to every model generated or template generated text before it is stored or sent.
