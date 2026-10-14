import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import { copyProblems, pageText } from "@/test/copy-rules";
import { renderRoute, mockSignedIn, mockSignedOut } from "@/test/render";

type Case = { path: string; heading: string | RegExp; medical?: boolean };

const CASES: Case[] = [
  { path: "/", heading: "Overview" },
  { path: "/plan", heading: "Monday plan" },
  { path: "/insights", heading: "Trends" },
  { path: "/assistant", heading: "Assistant" },
  { path: "/products", heading: "Products" },
  { path: "/products/new", heading: "Add product" },
  { path: "/products/new", heading: "Add product", medical: true },
  { path: "/products/p1", heading: "Anaj Ghar Black Pepper 50 g" },
  { path: "/products/p1?tab=stock", heading: "Anaj Ghar Black Pepper 50 g" },
  { path: "/products/p1?tab=prices", heading: "Anaj Ghar Black Pepper 50 g" },
  { path: "/products/p1?tab=sales", heading: "Anaj Ghar Black Pepper 50 g" },
  { path: "/products/p1/edit", heading: /^Edit / },
  { path: "/stock?tab=levels", heading: "Stock" },
  { path: "/stock?tab=batches", heading: "Stock" },
  { path: "/stock?tab=movements", heading: "Stock" },
  { path: "/stock?tab=counts", heading: "Stock" },
  { path: "/stock?tab=out", heading: "Stock" },
  { path: "/sales", heading: "Sales" },
  { path: "/sales/new", heading: "New bill" },
  { path: "/sales/b1", heading: "Bill B2610-00001" },
  { path: "/purchases", heading: "Purchases" },
  { path: "/purchases/new", heading: "New order" },
  { path: "/purchases/o1", heading: "Order PO2610-0009" },
  { path: "/settings?tab=business", heading: "Settings" },
  { path: "/settings?tab=planning", heading: "Settings" },
  { path: "/settings?tab=calendar", heading: "Settings" },
  { path: "/settings?tab=account", heading: "Settings" },
  { path: "/settings?tab=about", heading: "Settings" },
  { path: "/no-such-page", heading: "We could not find that page." },
];

async function settled() {
  await screen.findByRole("heading", { level: 1 }, { timeout: 8000 });
  await waitFor(() => expect(document.querySelector(".skeleton")).toBeNull(), { timeout: 8000 });
}

describe("every route renders plain, rule-following text", () => {
  for (const { path, heading, medical } of CASES) {
    const name = `${path}${medical ? " (medical)" : ""}`;
    it(
      name,
      async () => {
        mockSignedIn(medical ? { business_type: "medical", slug: "med" } : {});
        renderRoute(path);
        await screen.findByRole("heading", { name: heading, level: 1 }, { timeout: 8000 });
        await settled();
        const problems = copyProblems(pageText());
        expect(problems).toEqual([]);
      },
      20000,
    );
  }

  it("/login", async () => {
    mockSignedOut();
    renderRoute("/login");
    await screen.findByLabelText("Email");
    expect(copyProblems(pageText())).toEqual([]);
  });
});

describe("accessibility", () => {
  const checked: [string, string][] = [
    ["login", "/login"],
    ["overview", "/"],
    ["products", "/products"],
    ["sale entry", "/sales/new"],
  ];
  for (const [label, path] of checked) {
    it(`${label} has no axe violations`, async () => {
      if (path === "/login") mockSignedOut();
      else mockSignedIn();
      const { container } = renderRoute(path);
      if (path === "/login") await screen.findByLabelText("Email");
      else {
        await screen.findByRole("heading", { level: 1 }, { timeout: 8000 });
        await settled();
      }
      const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
      expect(results).toHaveNoViolations();
    }, 20000);
  }
});
