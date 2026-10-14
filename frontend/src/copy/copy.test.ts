import { describe, expect, it } from "vitest";
import { copyProblems } from "@/test/copy-rules";
import { common } from "./common";
import { login } from "./login";
import { overview } from "./overview";
import { products } from "./products";
import { purchases } from "./purchases";
import { sales } from "./sales";
import { settings } from "./settings";
import { shell } from "./shell";
import { stock } from "./stock";

/** Walks a copy object and returns every string, calling message functions with sample values. */
function collect(value: unknown, path: string, out: [string, string][]): void {
  if (typeof value === "string") {
    out.push([path, value]);
  } else if (typeof value === "function") {
    const samples: unknown[][] = [
      ["Sample", "Other", "Third"],
      [1, 2, 3],
      [5, "Sample", "Other"],
      [["One", "Two"]],
    ];
    for (const args of samples) {
      try {
        const result = (value as (...a: unknown[]) => unknown)(...args);
        if (typeof result === "string") out.push([path, result]);
      } catch {
        // A function that cannot take these samples is covered by the rendered page test.
      }
    }
  } else if (Array.isArray(value)) {
    value.forEach((item, index) => collect(item, `${path}[${index}]`, out));
  } else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) collect(child, `${path}.${key}`, out);
  }
}

const modules = { common, login, overview, products, purchases, sales, settings, shell, stock };

describe("copy modules follow the writing rules", () => {
  for (const [name, module] of Object.entries(modules)) {
    it(`${name} has no dashes, exclamation marks, emoji or banned words`, () => {
      const strings: [string, string][] = [];
      collect(module, name, strings);
      expect(strings.length).toBeGreaterThan(5);
      const problems = strings.flatMap(([path, text]) =>
        copyProblems(text).map((problem) => `${path}: ${problem}: ${text}`),
      );
      expect(problems).toEqual([]);
    });
  }

  it("never marks required fields with an asterisk", () => {
    for (const [name, module] of Object.entries(modules)) {
      const strings: [string, string][] = [];
      collect(module, name, strings);
      const stars = strings.filter(([, text]) => text.includes("*"));
      expect(stars).toEqual([]);
    }
  });

  it("uses sentence case for buttons and headings it names", () => {
    const labels = [
      shell.nav.plan,
      products.addProduct,
      sales.newBill,
      purchases.newOrder,
      stock.startCount,
    ];
    for (const label of labels) {
      const words = label.split(" ").slice(1);
      expect(words.filter((w) => /^[A-Z][a-z]+$/.test(w))).toEqual([]);
    }
  });
});
