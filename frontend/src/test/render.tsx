import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { Suspense } from "react";
import { http, HttpResponse } from "msw";
import { createQueryClient, Providers } from "@/app";
import { routes } from "@/routes";
import { server } from "./server";
import { dataHandlers } from "./fixtures";
import { session } from "./handlers";

/** Signs in through the refresh cookie and answers every data request with fixtures. */
export function mockSignedIn(tenantOverrides: Partial<typeof session.tenant> = {}) {
  server.use(
    http.post("/api/v1/auth/refresh", () =>
      HttpResponse.json({ ...session, tenant: { ...session.tenant, ...tenantOverrides } }),
    ),
    ...dataHandlers,
  );
}

export function mockSignedOut() {
  server.use(
    http.post("/api/v1/auth/refresh", () =>
      HttpResponse.json(
        { error: { code: "UNAUTHENTICATED", message: "x", details: [], request_id: "r1" } },
        { status: 401 },
      ),
    ),
    ...dataHandlers,
  );
}

export function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = createQueryClient();
  const view = render(
    <Providers client={client}>
      <Suspense fallback={null}>
        <RouterProvider router={router} />
      </Suspense>
    </Providers>,
  );
  return { ...view, router, client };
}

export async function waitForHeading(name: string | RegExp) {
  return screen.findByRole("heading", { name, level: 1 }, { timeout: 5000 });
}
