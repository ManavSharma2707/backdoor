/**
 * Every number and date the person reads goes through here (ui-copywriting.md section 6).
 * Money and quantities arrive from the API as strings and are only formatted, never calculated.
 */

type Numeric = string | number | null | undefined;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

const inr0 = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const inr2 = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const grouped = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });

function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** `₹1,82,340` or, with two decimals, `₹1,82,340.50`. Empty text when there is no value. */
export function money(value: Numeric, decimals: 0 | 2 = 0): string {
  const n = toNumber(value);
  if (n === null) return "";
  const text = (decimals === 0 ? inr0 : inr2).format(Math.abs(n));
  // A value that rounds to zero is shown without a sign.
  const isZero = Number(text.replace(/[^0-9.]/g, "")) === 0;
  return n < 0 && !isZero ? `-${text}` : text;
}

/** Under 1 lakh in full, then `₹1.8 lakh`, then `₹1.2 crore`. */
export function compactMoney(value: Numeric): string {
  const n = toNumber(value);
  if (n === null) return "";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs < 100_000) return `${sign}${inr0.format(Math.round(abs))}`;
  const lakh = Math.round((abs / 100_000) * 10) / 10;
  if (lakh < 100) return `${sign}₹${trimZero(lakh)} lakh`;
  const crore = Math.round((abs / 10_000_000) * 10) / 10;
  return `${sign}₹${trimZero(crore)} crore`;
}

function trimZero(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** `1,250` and `12.5`. Up to three decimals, never trailing zeros. */
export function quantity(value: Numeric): string {
  const n = toNumber(value);
  if (n === null) return "";
  const text = grouped.format(Math.abs(n));
  return n < 0 && Number(text.replace(/,/g, "")) !== 0 ? `-${text}` : text;
}

/** A change in stock with an explicit sign: `+12`, `-4`, `0`. */
export function signedQuantity(value: Numeric): string {
  const n = toNumber(value);
  if (n === null) return "";
  const text = quantity(n);
  return n > 0 ? `+${text}` : text;
}

/** `0.31` becomes `31%`. Pass `decimals` for accuracy tables. */
export function percentOfOne(value: Numeric, decimals = 0): string {
  const n = toNumber(value);
  if (n === null) return "";
  return `${(n * 100).toFixed(decimals)}%`;
}

/** `"5.00"` becomes `5%`. For values that already are percentages, such as a GST rate. */
export function percentValue(value: Numeric, decimals = 0): string {
  const n = toNumber(value);
  if (n === null) return "";
  return `${n.toFixed(decimals)}%`.replace(/\.0+%$/, "%");
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${quantity(count)} ${count === 1 ? one : many}`;
}

// ---------------------------------------------------------------------------- dates

type Ymd = { y: number; m: number; d: number };

function parseDate(value: string): Ymd | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
}

function istParts(instant: string | Date): (Ymd & { h: number; min: number }) | null {
  const ms = (typeof instant === "string" ? new Date(instant) : instant).getTime();
  if (Number.isNaN(ms)) return null;
  const shifted = new Date(ms + IST_OFFSET_MS);
  return {
    y: shifted.getUTCFullYear(),
    m: shifted.getUTCMonth() + 1,
    d: shifted.getUTCDate(),
    h: shifted.getUTCHours(),
    min: shifted.getUTCMinutes(),
  };
}

function toIso({ y, m, d }: Ymd): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function dayNumber({ y, m, d }: Ymd): number {
  return Date.UTC(y, m - 1, d) / DAY_MS;
}

/** The business date in Asia/Kolkata for an instant (default now), as `YYYY-MM-DD`. */
export function todayIso(now: Date = new Date()): string {
  const parts = istParts(now);
  return parts ? toIso(parts) : "";
}

export function addDays(iso: string, days: number): string {
  const p = parseDate(iso);
  if (!p) return "";
  const date = new Date(Date.UTC(p.y, p.m - 1, p.d) + days * DAY_MS);
  return toIso({ y: date.getUTCFullYear(), m: date.getUTCMonth() + 1, d: date.getUTCDate() });
}

export function daysBetween(fromIso: string, toIsoDate: string): number {
  const a = parseDate(fromIso);
  const b = parseDate(toIsoDate);
  if (!a || !b) return 0;
  return dayNumber(b) - dayNumber(a);
}

/** `12 Oct 2026` from a business date (`2026-10-12`) or an instant (shown in IST). */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const p = value.length > 10 ? istParts(value) : parseDate(value);
  return p ? `${p.d} ${MONTHS[p.m - 1]} ${p.y}` : "";
}

/** `12 Oct` without the year. */
export function formatDayMonth(value: string | null | undefined): string {
  if (!value) return "";
  const p = value.length > 10 ? istParts(value) : parseDate(value);
  return p ? `${p.d} ${MONTHS[p.m - 1]}` : "";
}

/** `6:02 am` in IST. */
export function formatTime(instant: string | null | undefined): string {
  if (!instant) return "";
  const p = istParts(instant);
  if (!p) return "";
  const hour = p.h % 12 === 0 ? 12 : p.h % 12;
  return `${hour}:${String(p.min).padStart(2, "0")} ${p.h < 12 ? "am" : "pm"}`;
}

export function formatDateTime(instant: string | null | undefined): string {
  if (!instant) return "";
  return `${formatDate(instant)}, ${formatTime(instant)}`;
}

/** `Week of 12 Oct` */
export function weekLabel(weekStart: string): string {
  return `Week of ${formatDayMonth(weekStart)}`;
}

/** `12 to 18 Oct 2026`, `28 Sep to 4 Oct 2026`, `28 Dec 2026 to 3 Jan 2027`. */
export function dateRange(from: string, to: string): string {
  const a = parseDate(from);
  const b = parseDate(to);
  if (!a || !b) return "";
  if (from === to) return formatDate(from);
  if (a.y !== b.y) return `${formatDate(from)} to ${formatDate(to)}`;
  if (a.m !== b.m) return `${a.d} ${MONTHS[a.m - 1]} to ${b.d} ${MONTHS[b.m - 1]} ${b.y}`;
  return `${a.d} to ${b.d} ${MONTHS[b.m - 1]} ${b.y}`;
}

/** `in 3 days (16 Oct)`, `today`, `tomorrow`, `yesterday`, `3 days ago (9 Oct)`. */
export function relativeDays(iso: string, today: string): string {
  if (!parseDate(iso) || !parseDate(today)) return "";
  const diff = daysBetween(today, iso);
  if (diff === 0) return "today";
  if (diff === 1) return "tomorrow";
  if (diff === -1) return "yesterday";
  const label = formatDayMonth(iso);
  return diff > 0 ? `in ${diff} days (${label})` : `${-diff} days ago (${label})`;
}

/** Turns what a person typed (`12 Oct 2026`, `12/10/2026`, `2026-10-12`) into an ISO date. */
export function parseTypedDate(text: string): string | null {
  const t = text.trim();
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (iso) return validIso(Number(iso[1]), Number(iso[2]), Number(iso[3]));
  const slash = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/.exec(t);
  if (slash) return validIso(Number(slash[3]), Number(slash[2]), Number(slash[1]));
  const words = /^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$/.exec(t);
  if (words) {
    const name = (words[2] ?? "").toLowerCase();
    const month = MONTHS.findIndex((m) => name.startsWith(m.toLowerCase()));
    if (month >= 0) return validIso(Number(words[3]), month + 1, Number(words[1]));
  }
  return null;
}

function validIso(y: number, m: number, d: number): string | null {
  if (m < 1 || m > 12 || d < 1) return null;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return d <= last ? toIso({ y, m, d }) : null;
}

/** The Monday of the week that holds `iso`. */
export function weekStartOf(iso: string): string {
  const p = parseDate(iso);
  if (!p) return "";
  const weekday = (new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay() + 6) % 7;
  return addDays(iso, -weekday);
}
