import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { product } from "@/test/fixtures";
import { renderRoute, mockSignedIn, waitForHeading } from "@/test/render";

async function open(tenant: Record<string, string> = {}) {
  mockSignedIn(tenant);
  const user = userEvent.setup();
  renderRoute("/products/new");
  await waitForHeading("Add product");
  await screen.findByRole("option", { name: "Spices and masalas" });
  return user;
}

describe("product form", () => {
  it("names every missing field in plain words on submit", async () => {
    const user = await open();
    await user.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Enter a name.")).toBeInTheDocument();
    expect(screen.getByText("Enter a SKU.")).toBeInTheDocument();
    expect(screen.getByText("Pick a category.")).toBeInTheDocument();
    expect(screen.getByText("Pick a GST rate.")).toBeInTheDocument();
    expect(screen.getAllByText("Enter an amount like 68 or 68.50.")).toHaveLength(2);
  });

  it("does not let the selling price pass the MRP", async () => {
    const user = await open();
    await user.type(screen.getByLabelText("MRP"), "50");
    await user.type(screen.getByLabelText("Selling price"), "60");
    await user.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Selling price cannot be more than MRP.")).toBeInTheDocument();
  });

  it("marks optional fields with the word and never with an asterisk", async () => {
    await open();
    expect(screen.getAllByText("Optional").length).toBeGreaterThan(3);
    expect(document.body.textContent).not.toContain("*");
  });

  it("shows medicine details only for medical businesses", async () => {
    await open();
    expect(screen.queryByText("Medicine details")).not.toBeInTheDocument();
    document.body.innerHTML = "";
    const medical = await open({ business_type: "medical" });
    expect(medical).toBeDefined();
    await waitFor(() => expect(screen.getAllByText("Medicine details").length).toBeGreaterThan(0));
    expect(screen.getAllByLabelText("Schedule (for your records)").length).toBeGreaterThan(0);
  });

  it("creates the product and goes to its page", async () => {
    const user = await open();
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/products", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(product, { status: 201 });
      }),
    );
    await user.type(screen.getByLabelText("Name"), "Anaj Ghar Black Pepper 50 g");
    await user.type(screen.getByLabelText("SKU"), "FA-031");
    await user.selectOptions(screen.getByLabelText("Category"), "c1");
    await user.type(screen.getByLabelText("MRP"), "68");
    await user.type(screen.getByLabelText("Selling price"), "68");
    await user.selectOptions(screen.getByLabelText("GST rate"), "t5");
    await user.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("Product added.")).toBeInTheDocument();
    expect(sent).toMatchObject({
      sku: "FA-031",
      mrp: "68",
      selling_price: "68",
      tax_rate_id: "t5",
      category_id: "c1",
    });
  });

  it("puts the server's field message on the field", async () => {
    const user = await open();
    server.use(
      http.post("/api/v1/products", () =>
        HttpResponse.json(
          {
            error: {
              code: "CONFLICT",
              message: "That SKU is already used.",
              details: [{ field: "sku", issue: "That SKU is already used." }],
              request_id: "r",
            },
          },
          { status: 409 },
        ),
      ),
    );
    await user.type(screen.getByLabelText("Name"), "Pepper");
    await user.type(screen.getByLabelText("SKU"), "FA-031");
    await user.selectOptions(screen.getByLabelText("Category"), "c1");
    await user.type(screen.getByLabelText("MRP"), "68");
    await user.type(screen.getByLabelText("Selling price"), "68");
    await user.selectOptions(screen.getByLabelText("GST rate"), "t5");
    await user.click(screen.getByRole("button", { name: "Add product" }));
    expect(await screen.findByText("That SKU is already used.")).toBeInTheDocument();
  });
});
