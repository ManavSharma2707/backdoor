import { http, HttpResponse } from "msw";

export const API = "/api/v1";

export const session = {
  access_token: "test-access-token",
  token_type: "bearer",
  expires_in: 900,
  user: { id: "u1", email: "owner@demo.test", full_name: "Test Owner", role: "owner" },
  tenant: {
    id: "t1",
    slug: "test-shop",
    name: "Test Stores",
    business_type: "fmcg",
    is_synthetic: true,
  },
};

// Filled in by fixtures.ts, so this file stays small.
export const handlers = [
  http.post(`${API}/auth/refresh`, () =>
    HttpResponse.json(
      { error: { code: "UNAUTHENTICATED", message: "x", details: [], request_id: "r1" } },
      { status: 401 },
    ),
  ),
];
