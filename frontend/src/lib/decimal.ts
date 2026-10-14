/**
 * Exact money arithmetic for what is shown on the bill form before it is saved.
 * The server prices and totals every saved bill. These helpers only avoid float drift.
 */

const PLAIN = /^-?\d+(\.\d+)?$/;

/** `"12.5"` to 12500n at scale 3. Returns null when the text is not a plain decimal. */
export function toScaled(text: string, scale: number): bigint | null {
  const t = text.trim();
  if (!PLAIN.test(t)) return null;
  const negative = t.startsWith("-");
  const [whole = "0", fraction = ""] = t.replace("-", "").split(".");
  const padded = (fraction + "0".repeat(scale)).slice(0, scale);
  const value = BigInt(whole + padded);
  return negative ? -value : value;
}

/** Rounds half up from `scale` decimals to paise. */
function toPaise(value: bigint, scale: number): bigint {
  const divisor = 10n ** BigInt(scale - 2);
  const half = divisor / 2n;
  return value >= 0n ? (value + half) / divisor : -((-value + half) / divisor);
}

/** Quantity (up to 3 decimals) times unit price, minus discount, in paise. Null on bad input. */
export function lineTotalPaise(quantity: string, price: string, discount: string): bigint | null {
  const q = toScaled(quantity, 3);
  const p = toScaled(price, 4);
  const d = toScaled(discount === "" ? "0" : discount, 2);
  if (q === null || p === null || d === null) return null;
  return toPaise(q * p, 7) - d;
}

/** Paise as a plain decimal string such as `"182340.50"`, for `money()`. */
export function paiseToString(paise: bigint): string {
  const negative = paise < 0n;
  const abs = negative ? -paise : paise;
  const whole = abs / 100n;
  const cents = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole}.${cents}`;
}
