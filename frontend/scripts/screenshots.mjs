// Takes screenshots of the running app at desktop and phone widths for the design review.
//   DEMO_OWNER_PASSWORD=... node scripts/screenshots.mjs [email] [route ...]
// Needs the stack up (make up) and the Vite dev server on :5173. Output: frontend/screenshots/
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.env.APP_URL ?? "http://localhost:5173";
const password = process.env.DEMO_OWNER_PASSWORD;
if (!password) throw new Error("Set DEMO_OWNER_PASSWORD");
const [email = "owner.fmcg-a@backroom-demo.com", ...routes] = process.argv.slice(2);
const targets = routes.length ? routes : ["/"];
const sizes = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

mkdirSync("screenshots", { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const tag = email.split("@")[0].replace(/[^a-z0-9]+/gi, "-");

for (const size of sizes) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.error("page error:", error.message));
  page.on("console", (message) => {
    if (message.type() === "error") console.error("console error:", message.text());
  });
  await page.goto(`${base}/login`);
  await page.getByLabel("Email").waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `screenshots/${size.name}-login.png` });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`${base}/`);
  for (const route of targets) {
    await page.goto(`${base}${route}`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
    const slug =
      route === "/" ? "overview" : route.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "");
    await page.screenshot({ path: `screenshots/${size.name}-${tag}-${slug}.png`, fullPage: true });
  }
  await context.close();
}
await browser.close();
