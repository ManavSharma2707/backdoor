import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { ApiError, api, onSessionEnded, refreshSession, serverStatus, tokenStore } from "./api";

const BASE = "/api/v1";
const envelope = (
  code: string,
  message: string,
  status: number,
  headers: Record<string, string> = {},
) =>
  HttpResponse.json(
    {
      error: {
        code,
        message,
        details: [{ field: "quantity", issue: "must be > 0" }],
        request_id: "req-1",
      },
    },
    { status, headers },
  );

afterEach(() => {
  onSessionEnded(null);
  serverStatus.set("ok");
});

describe("api client", () => {
  it("sends the bearer token and parses JSON", async () => {
    tokenStore.set("abc");
    let seen: string | null = null;
    server.use(
      http.get(`${BASE}/ping`, ({ request }) => {
        seen = request.headers.get("authorization");
        return HttpResponse.json({ ok: true });
      }),
    );
    await expect(api("/ping")).resolves.toEqual({ ok: true });
    expect(seen).toBe("Bearer abc");
  });

  it("keeps the token out of web storage", async () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    server.use(
      http.post(`${BASE}/auth/refresh`, () =>
        HttpResponse.json({ access_token: "t", expires_in: 900, user: {}, tenant: {} }),
      ),
    );
    await refreshSession();
    expect(tokenStore.get()).toBe("t");
    expect(local).not.toHaveBeenCalled();
    expect(JSON.stringify({ ...localStorage })).not.toContain("t");
    local.mockRestore();
  });

  it("parses the error envelope into an ApiError", async () => {
    tokenStore.set("abc");
    server.use(
      http.post(`${BASE}/sales`, () =>
        envelope("VALIDATION_ERROR", "Quantity must be more than zero.", 422),
      ),
    );
    const error = await api("/sales", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.code).toBe("VALIDATION_ERROR");
    expect(apiError.message).toBe("Quantity must be more than zero.");
    expect(apiError.requestId).toBe("req-1");
    expect(apiError.fieldMessage("quantity")).toBe("must be > 0");
  });

  it("reads Retry-After on a refused login", async () => {
    server.use(
      http.post(`${BASE}/auth/login`, () =>
        envelope("UNAUTHENTICATED", "x", 401, { "Retry-After": "900" }),
      ),
    );
    const error = (await api("/auth/login", { method: "POST", body: {}, anonymous: true }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.retryAfter).toBe(900);
  });

  it("falls back to the plain server message when the body is not an envelope", async () => {
    tokenStore.set("abc");
    server.use(
      http.get(`${BASE}/boom`, () => new HttpResponse("<html>bad gateway</html>", { status: 502 })),
    );
    const error = (await api("/boom").catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("INTERNAL");
    expect(error.message).toMatch(/Something went wrong on our side/);
  });

  it("refreshes once on 401 and retries the request", async () => {
    tokenStore.set("old");
    let refreshes = 0;
    const tokens: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/auth/refresh`, () => {
        refreshes += 1;
        return HttpResponse.json({ access_token: "new", expires_in: 900, user: {}, tenant: {} });
      }),
      http.get(`${BASE}/data`, ({ request }) => {
        const token = request.headers.get("authorization");
        tokens.push(token);
        return token === "Bearer new"
          ? HttpResponse.json({ ok: 1 })
          : envelope("UNAUTHENTICATED", "x", 401);
      }),
    );
    await expect(api("/data")).resolves.toEqual({ ok: 1 });
    expect(refreshes).toBe(1);
    expect(tokens).toEqual(["Bearer old", "Bearer new"]);
  });

  it("shares one refresh between requests that fail together", async () => {
    tokenStore.set("old");
    let refreshes = 0;
    server.use(
      http.post(`${BASE}/auth/refresh`, async () => {
        refreshes += 1;
        await new Promise((resolve) => setTimeout(resolve, 30));
        return HttpResponse.json({ access_token: "new", expires_in: 900, user: {}, tenant: {} });
      }),
      http.get(`${BASE}/data/:id`, ({ request }) =>
        request.headers.get("authorization") === "Bearer new"
          ? HttpResponse.json({ ok: 1 })
          : envelope("UNAUTHENTICATED", "x", 401),
      ),
    );
    const results = await Promise.all([api("/data/1"), api("/data/2"), api("/data/3")]);
    expect(results).toHaveLength(3);
    expect(refreshes).toBe(1);
  });

  it("ends the session when the refresh fails", async () => {
    tokenStore.set("old");
    const ended = vi.fn();
    onSessionEnded(ended);
    server.use(
      http.post(`${BASE}/auth/refresh`, () => envelope("UNAUTHENTICATED", "x", 401)),
      http.get(`${BASE}/data`, () => envelope("UNAUTHENTICATED", "x", 401)),
    );
    await expect(api("/data")).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalledTimes(1);
    expect(tokenStore.get()).toBeNull();
  });

  it("does not try to refresh an anonymous request", async () => {
    let refreshes = 0;
    server.use(
      http.post(`${BASE}/auth/refresh`, () => {
        refreshes += 1;
        return HttpResponse.json({});
      }),
      http.post(`${BASE}/auth/login`, () =>
        envelope("UNAUTHENTICATED", "Email or password is not right.", 401),
      ),
    );
    await expect(
      api("/auth/login", { method: "POST", body: {}, anonymous: true }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(refreshes).toBe(0);
  });

  it("sends the idempotency key and drops empty query values", async () => {
    tokenStore.set("abc");
    let url = "";
    let key: string | null = null;
    server.use(
      http.post(`${BASE}/sales`, ({ request }) => {
        url = request.url;
        key = request.headers.get("idempotency-key");
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    await api("/sales", {
      method: "POST",
      body: {},
      idempotencyKey: "key-12345",
      query: { a: "1", b: "", c: null, d: 0 },
    });
    expect(key).toBe("key-12345");
    expect(new URL(url).search).toBe("?a=1&d=0");
  });

  it("reports a network failure in plain words", async () => {
    tokenStore.set("abc");
    server.use(http.get(`${BASE}/down`, () => HttpResponse.error()));
    const error = (await api("/down", { retryOnTimeout: false }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.code).toBe("NETWORK");
    expect(error.message).toBe(
      "We could not reach the server. Check your connection and try again.",
    );
    expect(serverStatus.get()).toBe("unreachable");
  });
});
