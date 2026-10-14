import { lineTotalPaise, paiseToString, toScaled } from "@/lib/decimal";
import type { BatchRow, Product, SaleCreate } from "@/types/models";

export type EntryLine = {
  key: string;
  product: Product;
  quantity: string;
  price: string;
  discount: string;
  /** Empty means the server picks batches, earliest expiry first. */
  batchId: string;
  /** Loaded for batch tracked products so the person can see expiry and change the batch. */
  batches: BatchRow[] | null;
};

export type LineProblems = { quantity?: boolean; price?: boolean; discount?: boolean };

let counter = 0;
export const nextLineKey = () => `line-${++counter}`;

function plain(value: string): string {
  return value.replace(/,/g, "").trim();
}

/** A new line for the product, or the existing line with one more unit. */
export function addProduct(lines: EntryLine[], product: Product): EntryLine[] {
  const at = lines.findIndex((line) => line.product.id === product.id);
  if (at >= 0) {
    return lines.map((line, index) => {
      if (index !== at) return line;
      const current = toScaled(plain(line.quantity), 3) ?? 0n;
      const next = current + 1000n;
      const whole = next / 1000n;
      const fraction = (next % 1000n).toString().padStart(3, "0").replace(/0+$/, "");
      return { ...line, quantity: fraction ? `${whole}.${fraction}` : String(whole) };
    });
  }
  return [
    ...lines,
    {
      key: nextLineKey(),
      product,
      quantity: "1",
      price: String(Number(product.selling_price)),
      discount: "",
      batchId: "",
      batches: null,
    },
  ];
}

/** Stock the line can draw on: the chosen batch, or the product total. */
export function availableFor(line: EntryLine): string {
  if (line.batchId && line.batches) {
    return line.batches.find((b) => b.batch_id === line.batchId)?.on_hand ?? line.product.on_hand;
  }
  return line.product.on_hand;
}

/** Quantity asked for is more than what is on hand. Compared as exact decimals. */
export function exceedsStock(line: EntryLine): boolean {
  const wanted = toScaled(plain(line.quantity), 3);
  const have = toScaled(plain(availableFor(line)), 3);
  return wanted !== null && have !== null && wanted > have;
}

export function problemsFor(line: EntryLine): LineProblems {
  const quantity = toScaled(plain(line.quantity), 3);
  const price = toScaled(plain(line.price), 4);
  const discount = line.discount.trim() === "" ? 0n : toScaled(plain(line.discount), 2);
  const total = lineTotalPaise(plain(line.quantity), plain(line.price), plain(line.discount));
  return {
    quantity:
      quantity === null || quantity <= 0n || !/^\d+(\.\d{1,3})?$/.test(plain(line.quantity)),
    price: price === null || price < 0n || !/^\d+(\.\d{1,4})?$/.test(plain(line.price)),
    discount:
      discount === null ||
      discount < 0n ||
      (line.discount.trim() !== "" && !/^\d+(\.\d{1,2})?$/.test(plain(line.discount))) ||
      (total !== null && total < 0n),
  };
}

export const hasProblems = (problems: LineProblems) =>
  Boolean(problems.quantity || problems.price || problems.discount);

/** Line total as a decimal string for display, or null while the numbers are incomplete. */
export function lineTotalText(line: EntryLine): string | null {
  const paise = lineTotalPaise(plain(line.quantity), plain(line.price), plain(line.discount));
  return paise === null ? null : paiseToString(paise);
}

export function billTotalText(lines: EntryLine[]): string {
  let sum = 0n;
  for (const line of lines) {
    const paise = lineTotalPaise(plain(line.quantity), plain(line.price), plain(line.discount));
    if (paise !== null) sum += paise;
  }
  return paiseToString(sum);
}

export function toRequest(lines: EntryLine[], paymentMode: SaleCreate["payment_mode"]): SaleCreate {
  return {
    payment_mode: paymentMode,
    lines: lines.map((line) => ({
      product_id: line.product.id,
      quantity: plain(line.quantity),
      unit_price: plain(line.price),
      discount_amount: line.discount.trim() === "" ? "0" : plain(line.discount),
      batch_id: line.batchId || undefined,
    })),
  };
}
