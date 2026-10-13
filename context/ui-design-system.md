# UI design system

Backroom is a working tool for shop owners and managers who read numbers all day. The interface should feel like a well kept ledger: calm, dense where it needs to be, plain, and quick. It must not look like a generated dashboard template.

Every visual value below is a token. Do not invent colours, sizes, radii or shadows in components. If a screen needs something new, add a token here first, then use it.

---

## 1. Design intent

- **Ledger, not showroom.** Paper-like background, thin rules, tabular numbers, restrained colour. Colour carries meaning (risk, status), not decoration.
- **Numbers first.** The most important number on a screen is the largest thing on it. Labels are short and sit above values.
- **One primary action per view.** Everything else is secondary or ghost.
- **Plain words.** Copy follows `ui-copywriting.md`.
- **No decoration for its own sake**: no gradients, glass, glow, blobs, stock illustrations, sparkle icons, emoji, confetti.

## 2. Anti-template checklist (review every screen against this)

The usual signs of a generated UI. None of these may appear:

1. Purple to blue gradients, gradient text, glowing borders, glassmorphism, blur backdrops.
2. A hero block with a big heading, subheading and two buttons. (This is an app. Page titles are plain.)
3. Rows of three equal "feature" cards with icon in a coloured circle.
4. Rounded 16 to 24 px cards with soft large shadows on everything.
5. Emoji, sparkle or wand icons, "AI" badges, robot avatars, shimmering text.
6. Default shadcn zinc theme or default Tailwind blue. Our palette is below.
7. Inter or system default fonts with huge bold headings. Our type is IBM Plex Sans with modest weights.
8. Every list shown as cards. Data is shown in tables, lists and rules.
9. Pill badges for everything. Use plain text with a small dot, and reserve filled chips for status that needs scanning.
10. Centred everything. Content is left aligned with a clear grid.
11. Generic dashboard stat tiles with tiny sparklines and green up arrows and percent deltas on every card. Show a delta only when it means something.
12. Marketing words in copy: "seamless", "powerful", "supercharge", "unlock", "effortless", "elevate", "insights at a glance", "welcome back" with a name and wave.
13. Em dashes or en dashes anywhere.
14. Over-explained empty states with illustrations. Use a sentence and one action.
15. Lottie, bouncy animations, parallax, skeleton shimmer gradients.
16. Equal visual weight everywhere. Create hierarchy with size, weight and spacing.
17. Rainbow charts. Max 3 series colours in a chart, and a muted default.
18. Identical spacing between every element. Group related things tightly, separate groups clearly.

A reviewer should not be able to guess a generator made it.

## 3. Colour tokens

Light theme only for the MVP (decision D-018 in `memory.md`). All text and UI colours meet WCAG AA (4.5:1 for text, 3:1 for large text and controls).

```css
@theme {
  /* surfaces */
  --color-bg:          #F5F3EE;  /* app background, warm paper */
  --color-surface:     #FFFFFF;  /* cards, tables, panels */
  --color-surface-2:   #FAF9F6;  /* table headers, subtle blocks, hover */
  --color-surface-3:   #ECE9E1;  /* neutral chips, selected row */
  --color-border:      #E2DED4;
  --color-border-strong: #CFC9BC;

  /* text */
  --color-text:        #1E1D1A;
  --color-text-2:      #55524A;
  --color-text-3:      #6F6A5F;  /* hints, placeholders. 4.5:1 on bg */
  --color-text-inverse:#FFFFFF;

  /* brand and actions */
  --color-primary:     #1F5A45;  /* deep green */
  --color-primary-hover:#184A39;
  --color-primary-soft:#E4EFE9;
  --color-link:        #1F5A45;
  --color-focus:       #2B5C8A;

  /* accent, used sparingly for festivals and highlights */
  --color-accent:      #B7791F;
  --color-accent-soft: #F6EBD3;

  /* semantic */
  --color-critical:    #A32A22;  --color-critical-soft: #FBE9E7;
  --color-high:        #B4530B;  --color-high-soft:     #FDEEDD;
  --color-medium:      #8A6A0B;  --color-medium-soft:   #FBF3D6;
  --color-ok:          #2D6A4F;  --color-ok-soft:       #E4EFE9;
  --color-info:        #2B5C8A;  --color-info-soft:     #E6EEF6;

  /* provenance tags */
  --color-observed:    #2B5C8A;
  --color-calculated:  #55524A;
  --color-assumed:     #8A6A0B;

  /* charts */
  --color-chart-1: #1F5A45;
  --color-chart-2: #B7791F;
  --color-chart-3: #2B5C8A;
  --color-chart-4: #A32A22;
  --color-chart-5: #7A6F5D;
  --color-chart-6: #4D8F8B;
  --color-chart-grid: #ECE8DE;
  --color-festival-band: #F6EBD3;
}
```
Rules: risk is always text plus colour, never colour alone. Primary green is for the one main button, links and selected navigation. Do not use green for "good numbers" unless it is a status (ok). Charts use chart-1 first, then 2 and 3. Festival bands use `festival-band` with a text label.

## 4. Typography

Families: **IBM Plex Sans** (UI), **IBM Plex Mono** (SKU codes, batch numbers, bill numbers). Self hosted via `@fontsource`. Weights used: 400, 500, 600 only. Numbers use `font-variant-numeric: tabular-nums` everywhere in tables and KPIs.

| Token | Size / line | Weight | Use |
|---|---|---|---|
| `text-xs` | 12 / 16 | 400 | Table meta, hints, provenance tags |
| `text-sm` | 13 / 18 | 400 | Table cells, secondary text |
| `text-base` | 14 / 20 | 400 | Body, form inputs on desktop |
| `text-md` | 16 / 24 | 500 | Inputs on mobile (prevents zoom), card titles |
| `text-lg` | 20 / 28 | 600 | Section headings |
| `text-xl` | 24 / 32 | 600 | Page titles |
| `text-kpi` | 28 / 32 | 600 | Primary numbers on KPI blocks |
| `text-display` | 36 / 40 | 600 | Used once: the planned spend on the Monday plan |

Letter spacing normal (no tracking tweaks). Sentence case everywhere. No all caps labels except the three provenance tags in `text-xs` with letter spacing 0.02em.

## 5. Spacing, radius, shadow, borders

- Spacing scale (4 px base): 4, 8, 12, 16, 20, 24, 32, 48. Within a group use 8 to 12. Between groups 24. Page padding 24 (16 on mobile).
- Radius: `--radius-sm 4px` (inputs, buttons, chips), `--radius-md 6px` (cards, tables, popovers), `--radius-lg 8px` (dialogs). Nothing rounder, no pills except status dots.
- Borders: 1 px `--color-border`. Cards and tables use borders, not shadows.
- Shadows only for floating layers: popover `0 4px 16px rgba(30,29,26,0.10)`, dialog and drawer `0 12px 32px rgba(30,29,26,0.16)`.
- Dividers: 1 px lines, used to separate rows and blocks.

## 6. Layout

- Grid: 12 columns, gutter 24, max content width 1360 px, centred only at very wide screens (left aligned inside the content area otherwise).
- **Shell**: fixed left sidebar 224 px (surface colour, right border), top bar 56 px (surface, bottom border), content area on `--color-bg`.
- Sidebar items (in order): Overview, Monday plan, Products, Sales, Purchases, Stock, Insights, Settings. 40 px rows, 16 px icon (lucide, stroke 1.5), label 14 px 500. Active item: `primary-soft` background, `primary` text, 2 px left bar. Business name and a small "Demo data" label at the top of the sidebar.
- Top bar: page search field (opens command palette), Assistant button (text "Assistant" with a chat bubble icon), user menu (name, Account, Sign out).
- Breakpoints: `sm 640`, `md 768`, `lg 1024`, `xl 1280`. Below `lg` the sidebar becomes a slide-over opened from a menu button. Below `md` tables get horizontal scroll with the first column sticky, and key screens (Overview, Monday plan, Stock) have a stacked variant. Mobile is supported for reading the plan and recording a sale, not as the only interface.
- Page header: title (`text-xl`), one line of context in `text-2`, actions right aligned. 24 px below.
- Demo label: a persistent 28 px strip below the top bar on synthetic tenants: "Demo data. Everything here is simulated." (`info-soft` background, `text-xs`). Not dismissible.

## 7. Components

Build as wrappers around Radix primitives in `components/ui/`. Each has all states: default, hover, focus-visible, active, disabled, loading, error where relevant. Focus ring: 2 px `--color-focus` with 2 px offset on every interactive element. Minimum target size 32 px (40 px on touch).

| Component | Spec |
|---|---|
| **Button** | Variants: primary (filled green, white text), secondary (white, border-strong, text), ghost (text only, hover surface-2), destructive (white with critical text and border, becomes filled critical only inside the confirm dialog). Sizes 32, 36 (default), 40. Loading shows a 14 px spinner and keeps width. Icon buttons need `aria-label` and a tooltip |
| **Input, Select, Textarea, Combobox** | 36 px height, border-strong, radius-sm, label above (`text-sm` 500), helper text below in `text-3`, error text below in `critical` with the field outlined in critical. No asterisks: mark optional fields with the word "Optional" next to the label. Inline validation on blur, summary on submit |
| **Number input** | Right aligned, tabular, unit suffix shown inside the field (for example "packs"), steppers only where a pack step matters |
| **Date picker** | Popover calendar (Radix popover plus a small calendar built with date-fns), text input accepts `12 Oct 2026` and `12/10/2026` |
| **Checkbox, Radio, Switch** | Standard sizes 16, switch 36 by 20. Labels clickable |
| **Tabs** | Underline style, 40 px, active has 2 px primary underline and text colour. Counts in `text-3` after the label, for example "Buy (41)" |
| **Table** | Header row `surface-2`, `text-xs` 500 `text-2`, sticky. Rows 40 px (compact 32 px), 1 px bottom border, hover `surface-2`, selected `surface-3`. Numbers right aligned with unit in the header, never repeated in cells. Zero shown as a thin hyphen-less "0". Sortable headers show a small caret. Row actions are an overflow menu, the primary action is a visible link. Pagination below: "1 to 50 of 118", previous and next buttons, page size select. Empty and loading states inside the table frame |
| **Expandable row** | Chevron at left, expanded area on `surface-2` with a two column key-value breakdown |
| **Badge and status** | Status chip: 20 px height, `text-xs` 500, soft background with matching text, radius-sm, used for statuses that need scanning (PO status, decision, stock status). Risk: a 8 px dot plus the word in matching text colour, no background |
| **Provenance tag** | `OBSERVED`, `CALCULATED`, `ASSUMED` in `text-xs`, colour per token, no background, 1 px bottom border dotted, tooltip explains |
| **Card / panel** | `surface`, 1 px border, radius-md, padding 16 or 20. Title `text-md` 500 with an optional action at right. Use panels only to group a coherent block, not to wrap every number |
| **KPI block** | Label (`text-sm` `text-2`), value (`text-kpi`), one hint line (`text-xs` `text-3`). Four to five across, separated by vertical rules inside one panel rather than separate cards |
| **Dialog** | Radix dialog, width 480 (form 560), radius-lg, title `text-lg`, footer with right aligned buttons (secondary then primary), focus trapped, Escape closes. Destructive dialogs name the thing being changed and the consequence |
| **Drawer** | Right side, 480 px, used for product detail quick view and line details |
| **Toast** | `sonner`, bottom right, plain text, no icon beyond default, 4 s. Errors stay until dismissed |
| **Tooltip** | 12 px text, delay 300 ms, never the only place important information lives |
| **Banner** | Full width inline block, `info-soft`, `medium-soft` for warnings, `critical-soft` for errors, text plus optional link action |
| **Empty state** | One sentence of what is missing, one sentence of what to do, one button. Left aligned inside the container |
| **Skeleton** | Static `surface-3` blocks with a very slow 1.6 s opacity pulse (0.6 to 1). No shimmer gradient |
| **Stepper (pack stepper)** | Minus, number field, plus buttons stepping by pack size, shows "= 20 units, 2 packs" |
| **Command palette** | `cmdk` dialog 560 wide: pages and products |

## 8. Data display rules

- Money: `₹1,82,340` (no decimals in KPIs and summaries, two decimals in bills, POs, unit costs). Lakh and crore compact form only in KPI blocks over 1 lakh ("₹1.8 lakh"). Negative amounts use a leading minus sign, never brackets or red unless it means a loss.
- Quantities: grouped with Indian separators, up to 3 decimals only for weighted goods. Show the unit once in the column header or after the number in free text ("20 packs").
- Percent: whole numbers in summaries (`31%`), one decimal in accuracy tables.
- Dates: `12 Oct 2026`. Week labels: "Week of 12 Oct". Relative dates only with the absolute date in a tooltip ("in 3 days, 16 Oct").
- Times: `6:02 am`.
- Always show "as of" where data freshness matters: "Data up to 11 Oct 2026".
- Risk words: Critical, High, Medium, Low. Confidence words: High, Fair, Low shown as "Forecast confidence: Fair" (maps to `medium`).

## 9. Charts (Recharts, tokens only)

- Types allowed: line (trends), bar (comparisons, cover by category as horizontal bars), stacked bar rarely. **No pie or donut. No 3D. No dual axes.**
- Style: 2 px lines, no dots except on hover, horizontal gridlines only (`chart-grid`), axis text `text-xs` `text-3`, no axis lines except the baseline, tooltip is a small surface panel with the date, series and values.
- Max 3 series at once, `chart-1` first. A selected series is full colour, others `text-3` at 40 percent when highlighting.
- Festival and season bands: `ReferenceArea` with `festival-band` fill and a label inside the top edge ("Diwali").
- Units in the axis title or chart title. Y axis starts at zero for bars.
- Every chart has a one line text summary above or below ("Sales were highest in the week of 20 Oct 2025.") for accessibility and clarity, and an Explain button that opens the assistant with the chart as context.
- Empty data shows a sentence, not an empty axis.

## 10. Assistant panel components

- **Panel**: docked right, 400 px (full height under the top bar), border left, `surface`. Header: "Assistant", history button, new chat, close. Footer composer.
- **Messages**: user messages right aligned on `surface-3` with 1 px border, radius-md, max 80 percent. Assistant messages left aligned, no avatar, a small "Assistant" label in `text-xs` `text-3` only on the first message of a turn. No typing dots: while working show the current friendly status line in `text-2` with a thin 2 px indeterminate progress line above the composer.
- **Blocks**: tables and metric cards render with the same components as the rest of the app, compact. Charts at 160 px height. Action cards: panel with a title, summary, item list (max 5, "and 7 more" expands), buttons "Confirm" (primary) and "Not now" (ghost), an expiry note.
- **Source chips**: small text links in `text-xs` underlined dotted: "Monday plan, 12 Oct". Clicking opens the referenced screen.
- **Follow-ups**: up to three outlined buttons (secondary, 32 px) under the last message.
- **Starter prompts** (empty state): six plain questions as a vertical list of ghost buttons, for example "What should I buy this week?", "What might run out before delivery?".
- **Composer**: textarea auto growing to 5 lines, Enter sends, Shift Enter new line, send button labelled "Send". Disclaimer line in `text-xs` `text-3`: "Answers use your saved data. Numbers come from your reports."
- Feedback: two small text buttons "Helpful" and "Not helpful" on hover or focus of the last message (tier C).

## 11. Motion

- Durations 120 to 160 ms, `ease-out`, for opacity and small translate (max 4 px). Dialogs fade and rise 8 px over 160 ms. Drawers slide 160 ms.
- No bounces, springs, parallax, auto playing animations, number count-ups.
- Respect `prefers-reduced-motion`: remove transforms, keep opacity changes under 80 ms.

## 12. Accessibility

- WCAG 2.2 AA. Keyboard reachable everything, visible focus, logical order. Skip link "Skip to content".
- Colour never the only signal. Text alternatives for charts. `aria-live="polite"` for toasts and assistant status. Form errors linked with `aria-describedby`.
- Tables use real `<table>` semantics, headers with `scope`. Expandable rows use `aria-expanded`.
- Test with keyboard only and with a screen reader on the Monday plan and sale entry.

## 13. Print and export consistency

PDF and Excel follow the same tokens where possible (fonts, colours for risk words, header fill `#F5F3EE`). Print stylesheet for the Monday plan page hides the sidebar and top bar and shows the demo label.

## 14. Implementation notes

- Tokens live in `src/styles/index.css` (`@theme`), nothing hard codes hex values in components (lint rule: grep for `#[0-9a-fA-F]{3,6}` in `src/components` and `src/features` outside the chart helpers fails the check).
- Storybook is not used. Create a hidden route `/_ui` (dev only) that renders every component and state for visual review.
- One screenshot review per screen against section 2 before marking a UI task done (store notes in `memory.md`).
