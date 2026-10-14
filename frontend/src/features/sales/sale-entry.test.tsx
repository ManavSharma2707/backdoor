import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderRoute, mockSignedIn, waitForHeading } from "@/test/render";

type Posted = { body: Record<string, unknown>; key: string | null };

function captureSales(response: Record<string, unknown> = {}) {
  const posted: Posted[] = [];
  server.use(
    http.post("/api/v1/sales", async ({ request }) => {
      posted.push({
        body: (await request.json()) as Record<string, unknown>,
        key: request.headers.get("idempotency-key"),
      });
      return HttpResponse.json(
        {
          id: "b9",
          bill_no: "B2610-00009",
          status: "completed",
          warnings: [],
          lines: [],
          ...response,
        },
        { status: 201 },
      );
    }),
  );
  return posted;
}

async function addPepper(user: ReturnType<typeof userEvent.setup>) {
  const search = await screen.findByRole("combobox", { name: "Find a product" });
  await user.type(search, "pepper");
  await screen.findByRole("option", { name: /Black Pepper/ });
  await user.keyboard("{Enter}");
  return search;
}

describe("sale entry keyboard flow", () => {
  it("adds a line with Enter and saves with Ctrl+Enter", async () => {
    mockSignedIn();
    const posted = captureSales();
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");

    const search = await addPepper(user);
    const quantity = await screen.findByLabelText("Quantity of Anaj Ghar Black Pepper 50 g");
    expect(quantity).toHaveValue("1");
    expect(search).toHaveValue("");
    expect(search).toHaveFocus();

    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]?.body).toMatchObject({
      payment_mode: "cash",
      lines: [{ product_id: "p1", quantity: "1", unit_price: "68", discount_amount: "0" }],
    });
    expect(posted[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText("Bill saved.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText(/^Quantity of /)).not.toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: "Find a product" })).toHaveFocus();
  });

  it("adding the same product again raises its quantity", async () => {
    mockSignedIn();
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");
    await addPepper(user);
    await addPepper(user);
    expect(await screen.findByLabelText("Quantity of Anaj Ghar Black Pepper 50 g")).toHaveValue(
      "2",
    );
    expect(screen.getAllByLabelText(/^Quantity of /)).toHaveLength(1);
  });

  it("warns when the quantity is more than the stock", async () => {
    mockSignedIn();
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");
    await addPepper(user);
    const quantity = await screen.findByLabelText("Quantity of Anaj Ghar Black Pepper 50 g");
    await user.clear(quantity);
    await user.type(quantity, "5");
    expect(
      await screen.findByText("Only 4 of Anaj Ghar Black Pepper 50 g in stock."),
    ).toBeInTheDocument();
  });

  it("does not save a bill with a bad quantity and says why", async () => {
    mockSignedIn();
    const posted = captureSales();
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");
    await addPepper(user);
    const quantity = await screen.findByLabelText("Quantity of Anaj Ghar Black Pepper 50 g");
    await user.clear(quantity);
    await user.type(quantity, "0");
    await user.click(screen.getByRole("button", { name: "Save bill" }));
    expect(await screen.findByText("Quantity must be more than zero.")).toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it("says there is nothing to save on an empty bill", async () => {
    mockSignedIn();
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");
    await user.click(screen.getByRole("button", { name: "Save bill" }));
    expect(await screen.findByText("Add at least one item.")).toBeInTheDocument();
  });

  it("offers to void a bill the server flags as a possible duplicate", async () => {
    mockSignedIn();
    captureSales({ warnings: [{ code: "POSSIBLE_DUPLICATE", message: "x", sale_id: "b1" }] });
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");
    await addPepper(user);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(
      await screen.findByText("A bill with the same items and total was saved a minute ago."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Void this bill" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the earlier bill/ })).toHaveAttribute(
      "href",
      "/sales/b9",
    );
  });

  it("shows the server's stock refusal without losing the lines", async () => {
    mockSignedIn();
    server.use(
      http.post("/api/v1/sales", () =>
        HttpResponse.json(
          {
            error: {
              code: "INSUFFICIENT_STOCK",
              message:
                "Only 4 packs of Black Pepper are in stock. Lower the quantity or record a delivery first.",
              details: [],
              request_id: "r",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderRoute("/sales/new");
    await waitForHeading("New bill");
    await addPepper(user);
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(
      await screen.findByText(/Only 4 packs of Black Pepper are in stock/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^Quantity of /)).toBeInTheDocument();
  });
});
