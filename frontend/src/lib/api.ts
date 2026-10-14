import { common } from "@/copy/common";

/**
 * The one place that talks to the API.
 *
 * - The access token lives in this module only (never in web storage).
 * - A 401 triggers one refresh shared by every request that failed at the same time, then one retry.
 * - Errors are parsed from the envelope in api-spec.md into `ApiError`.
 * - A request that times out is retried once, and subscribers hear that the server is waking up.
 */

export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export type ApiErrorDetail = { field: string; issue: string };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;
  readonly retryAfter: number | null;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    details?: ApiErrorDetail[];
    requestId?: string | null;
    retryAfter?: number | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? [];
    this.requestId = init.requestId ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }

  /** The error text for one form field, when the server named it. */
  fieldMessage(field: string): string | undefined {
    return this.details.find((d) => d.field === field || d.field.endsWith(`.${field}`))?.issue;
  }
}

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

// ------------------------------------------------------------------ token and session hooks

let accessToken: string | null = null;
let sessionEndedHandler: (() => void) | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (token: string | null) => {
    accessToken = token;
  },
};

export function onSessionEnded(handler: (() => void) | null): void {
  sessionEndedHandler = handler;
}

// ------------------------------------------------------------------ server status

export type ServerStatus = "ok" | "waking" | "unreachable";
let status: ServerStatus = "ok";
const listeners = new Set<() => void>();

export const serverStatus = {
  get: () => status,
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  set: (next: ServerStatus) => {
    if (status === next) return;
    status = next;
    listeners.forEach((l) => l());
  },
};

// ------------------------------------------------------------------ requests

export type Query = Record<string, string | number | boolean | null | undefined>;

export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
  idempotencyKey?: string;
  /** Skip the bearer token and the refresh on 401 (login, refresh itself). */
  anonymous?: boolean;
  /** Allow one retry after a timeout. Defaults to true for reads and keyed writes. */
  retryOnTimeout?: boolean;
  headers?: Record<string, string>;
};

const FIRST_TIMEOUT_MS = 20_000;
const RETRY_TIMEOUT_MS = 70_000;

function buildUrl(path: string, query?: Query): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${url}?${text}` : url;
}

class TimeoutError extends Error {}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  outer?: AbortSignal,
): Promise<Response> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forward = () => controller.abort();
  outer?.addEventListener("abort", forward);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) throw new TimeoutError();
    throw error;
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", forward);
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  const retryHeader = response.headers.get("Retry-After");
  const retryAfter = retryHeader && /^\d+$/.test(retryHeader) ? Number(retryHeader) : null;
  try {
    const body = (await response.json()) as {
      error?: {
        code?: string;
        message?: string;
        details?: ApiErrorDetail[];
        request_id?: string;
      };
    };
    if (body.error) {
      return new ApiError({
        status: response.status,
        code: body.error.code ?? "INTERNAL",
        message: body.error.message ?? common.errors.server,
        details: body.error.details ?? [],
        requestId: body.error.request_id ?? requestId,
        retryAfter,
      });
    }
  } catch {
    // Not JSON: fall through to the plain server error.
  }
  return new ApiError({
    status: response.status,
    code: response.status >= 500 ? "INTERNAL" : "UNKNOWN",
    message: common.errors.server,
    requestId,
    retryAfter,
  });
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  if (!options.anonymous && accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const init: RequestInit = {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    credentials: "same-origin",
  };
  const url = buildUrl(path, options.query);
  const mayRetry = options.retryOnTimeout ?? (method === "GET" || Boolean(options.idempotencyKey));
  try {
    const response = await fetchWithTimeout(url, init, FIRST_TIMEOUT_MS, options.signal);
    serverStatus.set("ok");
    return response;
  } catch (error) {
    if (error instanceof TimeoutError && mayRetry) {
      serverStatus.set("waking");
      try {
        const response = await fetchWithTimeout(url, init, RETRY_TIMEOUT_MS, options.signal);
        serverStatus.set("ok");
        return response;
      } catch (second) {
        serverStatus.set("unreachable");
        throw networkError(second);
      }
    }
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    serverStatus.set("unreachable");
    throw networkError(error);
  }
}

function networkError(_cause: unknown): ApiError {
  return new ApiError({ status: 0, code: "NETWORK", message: common.errors.network });
}

// ------------------------------------------------------------------ refresh (single flight)

let refreshing: Promise<boolean> | null = null;

export type SessionPayload = {
  access_token: string;
  expires_in: number;
  user: { id: string; email: string; full_name: string; role: string };
  tenant: { id: string; slug: string; name: string; business_type: string; is_synthetic: boolean };
};

let lastSession: SessionPayload | null = null;

/** The payload of the most recent successful refresh, for the auth provider to read. */
export const takeRefreshedSession = (): SessionPayload | null => {
  const value = lastSession;
  lastSession = null;
  return value;
};

/** Asks the server for a new access token using the refresh cookie. Shared by concurrent callers. */
export function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const response = await send("/auth/refresh", {
          method: "POST",
          anonymous: true,
          retryOnTimeout: true,
          headers: { "X-Requested-With": "backroom" },
        });
        if (!response.ok) {
          accessToken = null;
          return false;
        }
        const payload = (await response.json()) as SessionPayload;
        accessToken = payload.access_token;
        lastSession = payload;
        return true;
      } catch {
        accessToken = null;
        return false;
      } finally {
        // Cleared on the next tick so callers that joined this flight all see the same result.
        setTimeout(() => {
          refreshing = null;
        }, 0);
      }
    })();
  }
  return refreshing;
}

// ------------------------------------------------------------------ public helpers

async function request(path: string, options: RequestOptions): Promise<Response> {
  const tokenAtStart = accessToken;
  let response = await send(path, options);
  if (response.status === 401 && !options.anonymous) {
    // Another request may have refreshed while this one was in flight: retry with the new token.
    const refreshed =
      accessToken !== null && accessToken !== tokenAtStart ? true : await refreshSession();
    if (!refreshed) {
      sessionEndedHandler?.();
      throw await toApiError(response);
    }
    response = await send(path, options);
    if (response.status === 401) {
      accessToken = null;
      sessionEndedHandler?.();
    }
  }
  if (!response.ok) throw await toApiError(response);
  return response;
}

/** JSON in, JSON out. Throws `ApiError` for every non-2xx answer. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await request(path, options);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const get = <T>(path: string, query?: Query, signal?: AbortSignal) =>
  api<T>(path, { query, signal });

export const post = <T>(path: string, body?: unknown, options: RequestOptions = {}) =>
  api<T>(path, { ...options, method: "POST", body: body ?? {} });

export const patch = <T>(path: string, body: unknown, options: RequestOptions = {}) =>
  api<T>(path, { ...options, method: "PATCH", body });

export const put = <T>(path: string, body: unknown, options: RequestOptions = {}) =>
  api<T>(path, { ...options, method: "PUT", body });

export const del = <T>(path: string, options: RequestOptions = {}) =>
  api<T>(path, { ...options, method: "DELETE" });

/** Ping used by the sign in page to wake a sleeping server. Never throws. */
export async function wakeServer(): Promise<void> {
  try {
    await fetchWithTimeout(`${API_BASE}/health`, { method: "GET" }, FIRST_TIMEOUT_MS);
    serverStatus.set("ok");
  } catch {
    serverStatus.set("waking");
  }
}
