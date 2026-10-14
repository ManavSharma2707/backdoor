// Walks the main flows against the running stack: add a sale, receive a purchase, adjust stock.
//   DEMO_OWNER_PASSWORD=... node scripts/smoke.mjs [email]
// It writes real records to the demo database, so run it against demo data only.
import { chromium } from "@playwright/test";

const base = process.env.APP_URL ?? "http://localhost:5173";
const password = process.env.DEMO_OWNER_PASSWORD;
if (!password) throw new Error("Set DEMO_OWNER_PASSWORD");
const email = process.argv[2] ?? "owner.fmcg-a@backroom-demo.com";

const browser = await chromium.launch({ channel: "chrome" });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
page.on("pageerror", (error) => console.error("page error:", error.message));
const step = (text) => console.log(`ok  ${text}`);

await page.goto(`${base}/login`);
await page.getByLabel("Email").fill(email);
await page.getByLabel("Password", { exact: true }).fill(password);
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForURL(`${base}/`);
step("signed in");

// 1. A sale: search, Enter adds, Ctrl+Enter saves.
await page.goto(`${base}/sales/new`);
const search = page.getByRole("combobox", { name: "Find a product" });
await search.fill("FA-031");
await page.getByRole("option").first().waitFor();
await search.press("Enter");
await page
  .getByLabel(/^Quantity of /)
  .first()
  .waitFor();
await page.keyboard.press("Control+Enter");
await page
  .getByText("Bill saved.")
  .first()
  .waitFor({ timeout: 8000 })
  .catch(async () => {
    await page.screenshot({ path: "screenshots/smoke-fail.png" });
    throw new Error("sale did not save");
  });
step("sale saved with Ctrl+Enter");

// 2. A purchase: create an order, mark it as sent, receive it.
await page.goto(`${base}/purchases/new`);
await page.getByLabel("Supplier").selectOption({ label: "Om Sai Staples Wholesale" });
await page.getByLabel("Add a product").click();
await page.getByPlaceholder("Type to search.").fill("FA-031");
await page.locator("[cmdk-item]").first().waitFor();
await page.keyboard.press("Enter");
await page.getByRole("button", { name: "Save and mark as sent" }).click();
await page.getByText("Order created and marked as sent.").first().waitFor();
step("order created and sent");
await page.getByRole("button", { name: "Receive goods" }).first().click();
const receipt = page.getByRole("dialog");
await receipt.getByText("Open:").first().waitFor();
await page.waitForTimeout(500);
// Batch tracked lines need a batch number, an expiry date and an MRP.
for (const field of await receipt.getByLabel(/^Batch number of /).all()) await field.fill("SMOKE1");
for (const field of await receipt.getByLabel("Expiry date", { exact: true }).all()) {
  await field.fill("12 Oct 2027");
  await field.blur();
}
for (const field of await receipt.getByLabel(/^MRP of /).all()) await field.fill("99");
await receipt.getByRole("button", { name: "Receive goods" }).click();
await page
  .getByText("Goods received.")
  .first()
  .waitFor({ timeout: 8000 })
  .catch(async () => {
    await page.screenshot({ path: "screenshots/smoke-fail.png" });
    throw new Error("receipt did not save");
  });
step("goods received");

// 3. A stock adjustment.
await page.goto(`${base}/stock`);
await page.getByRole("button", { name: "Record adjustment" }).click();
const dialog = page.getByRole("dialog");
await dialog.getByLabel("Product", { exact: true }).click();
await page.getByPlaceholder("Type to search.").fill("FA-031");
await page.locator("[cmdk-item]").first().waitFor();
await page.keyboard.press("Enter");
await dialog.getByLabel("Change").fill("-1");
await dialog.getByRole("button", { name: "Save adjustment" }).click();
await page
  .getByText("Adjustment saved.")
  .first()
  .waitFor({ timeout: 8000 })
  .catch(async () => {
    await page.screenshot({ path: "screenshots/smoke-fail.png" });
    throw new Error("adjustment did not save");
  });
step("stock adjusted");

await browser.close();
