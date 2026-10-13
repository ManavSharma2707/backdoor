# Security specification

Goal: a production-grade auth and tenancy design for a small multi-tenant SaaS. Demo data is synthetic, but the foundation must be safe for real business data later.

---

## 1. Authentication

### Passwords
- Hash: **argon2id** via `argon2-cffi` `PasswordHasher` with parameters `time_cost=3, memory_cost=65536 (64 MiB), parallelism=2, hash_len=32, salt_len=16`. On Render free (512 MB, 0.1 CPU) 64 MiB is acceptable for a few logins, benchmark and record in `memory.md`. Lower `memory_cost` to 32768 if hashing exceeds 800 ms there.
- Rehash on login when `check_needs_rehash` is true.
- Policy: at least **12** characters (`D-054`), at most 128, must not equal the email or business name, must not be a common password (bundled list `app/assets/common_passwords.txt`, matched after lowercasing, letter swaps such as `@` for `a`, and trimming digits and symbols from the ends) or one character or block repeated, no composition rules (length matters more). Show a plain error: "Use at least 12 characters and avoid common passwords."
- Change password requires the current password and revokes all other sessions.
- No password hints, no security questions. Password reset by email is deferred. Owner reset is a CLI script for now (`python -m app.jobs.run reset-password --email ...`), logged.

### Login
- `POST /auth/login`: normalise email (lowercase, trim). Constant-time path: always run a hash verification, using a dummy hash when the user does not exist, so timing does not reveal accounts.
- Generic failure message for any credential error: "Email or password is not right."
- Lockout: after 5 consecutive failures within 15 minutes (the time of the latest failure is `users.last_failed_login_at`, `D-055`), `locked_until = now + 15 minutes`. Emails with no account are counted in memory the same way, so a locked answer never proves that an account exists. During lock return the same generic message with `Retry-After`, do not confirm the lock to unknown emails. Reset counter on success. Inactive users and inactive tenants cannot log in.
- Rate limits (slowapi and the `limits` library, in memory, single instance): login 10 per minute per IP and 10 per minute per email, refresh 30 per minute per IP, register 3 per hour per IP, demo login 10 per hour per IP, 120 per minute per signed in user for everything else. Answer 429 with `Retry-After` in the error envelope. Multi-instance needs a shared store (`D-058`).
- Audit: `auth.login.success`, `auth.login.failure` (email hash only, never the password), `auth.lockout`.

### Tokens
- **Access token**: JWT, `HS256`, secret `JWT_SECRET` (at least 32 random bytes, base64), 15 minutes. Claims: `sub` (user id), `tid` (tenant id), `role`, `iat`, `nbf`, `exp`, `iss` (`backroom`), `aud` (`backroom-web`), `jti`, `ver` (user `token_version` is not used, revocation happens through refresh). Validate every claim, require `exp`, algorithm pinned to HS256, reject `none`. Use PyJWT. Leeway 10 seconds.
- Held **in memory only** in the frontend (never `localStorage`, never `sessionStorage`).
- **Refresh token**: opaque 256-bit random value (`secrets.token_urlsafe(32)`), stored only as SHA-256 hash in `refresh_tokens`. Lifetime 14 days, sliding is not used (fixed from issue, rotation resets). Cookie `backroom_rt`: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`.
- **Rotation**: every `/auth/refresh` marks the presented token `rotated_at`, inserts a new token in the same `family_id`, sets `replaced_by_id`, and returns a new access token.
- **Reuse detection**: presenting a token that is already rotated or revoked revokes the whole family (`revoked_reason = reuse_detected`), clears the cookie, returns 401, writes `auth.refresh_reuse` audit. Allow a 10 second grace window for concurrent refreshes from the same browser (two tabs): if the token was rotated less than 10 seconds ago and the new token is unused, return 401 without revoking the family.
- **Logout** revokes the current token. **Logout all** revokes all families of the user. **Password change** revokes all other families.
- Expired tokens are purged by a daily cleanup in the Monday job (older than 30 days).

### CSRF
Refresh and logout are the only cookie authenticated endpoints. Controls: `SameSite=Lax` (cookie not sent on cross-site POST), required header `X-Requested-With: backroom`, and `Origin` header must be in `CORS_ORIGINS` (or absent for non-browser clients with the header present). All other endpoints use bearer tokens only, which are not sent automatically by browsers, so they are not CSRF exposed.

### Same-origin cookie strategy
The browser talks only to the Vercel domain. `vercel.json` rewrites `/api/:path*` to the Render URL, so the cookie is first party and works in Safari. Local dev uses the Vite proxy. If the Vercel rewrite buffers SSE or times out, the chat stream calls `VITE_CHAT_DIRECT_URL` with the bearer token (no cookies needed, CORS allowlist for that origin).

### Registration and demo login
- `ALLOW_REGISTRATION=false` by default. When true, `POST /auth/register` creates tenant plus owner with the same password policy and rate limit 3 per hour per IP.
- `DEMO_LOGIN_ENABLED=false` by default. When true, `POST /auth/demo-login` issues a normal session for a tenant with `is_synthetic = true` only, rate limited 10 per hour per IP. It is a convenience for the public demo and must stay off in any deployment holding real data. Document in README.

### Roles
`role` is in the token and checked server side. Only `owner` is used now. Dependency `require_role(min_role)` is attached to all routers. Adding staff and manager later means defining their allowed routes, not restructuring.

## 2. Tenant isolation (four layers)

1. **JWT claim `tid`** is the only source of tenant identity.
2. **Repository layer** (`core/repo.py`): `TenantRepo` adds `WHERE tenant_id = :tid` to every select, update and delete, and sets `tenant_id` on insert. Direct `session.query` of tenant models outside repositories is banned by a lint rule (a simple test that greps services for `select(` on tenant tables without `tenant_id`).
3. **Composite foreign keys** make cross-tenant references impossible at the database level.
4. **RLS deny-all** on every table plus revoked grants for `anon` and `authenticated` so the Supabase Data API exposes nothing. The backend connects with the owner role.

Tests: for each router a parametrised two-tenant test (create in A, read, update, delete from B returns 404). A database level test inserting a child row pointing to another tenant's parent fails. An RLS test connects as the `anon` role (if available locally via a test role) and confirms zero access.

## 3. Transport and headers

- HTTPS terminated by Render and Vercel. App sets `Strict-Transport-Security` only if behind HTTPS (`APP_ENV != local`).
- Backend response headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on auth and report responses, `X-Frame-Options: DENY`.
- Frontend (`vercel.json` headers): `Content-Security-Policy` with `default-src 'self'`, `script-src 'self'`, `style-src 'self' 'unsafe-inline'` (Tailwind inline styles from charts), `img-src 'self' data:`, `font-src 'self'`, `connect-src 'self' <render origin>` (and the Gemini origin is never needed in the browser), `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`. Plus `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` minimal. Fonts self-hosted (`@fontsource`).
- CORS: explicit origin list, methods and headers listed, `allow_credentials` only needed for the refresh route (set per route with a dedicated CORS config or handle by same-origin and skip CORS for it).

## 4. Input and output safety

- Pydantic validation on every body and query. Max lengths on all strings. Quantities and prices bounded. Dates sane.
- No raw SQL with string formatting. SQLAlchemy parameters only. The one place that builds SQL from names (sort whitelist) maps from an allowlist.
- Markdown in chat is rendered with `react-markdown` without raw HTML, with `rehype-sanitize`. Links open with `rel="noopener noreferrer"` and only `http`, `https`, `mailto`.
- File exports use fixed templates, escape cell values that start with `=`, `+`, `-`, `@` in CSV and Excel text columns (formula injection protection) by prefixing a single quote or storing as strings explicitly.
- Uploads: none in the MVP.
- Error responses never include stack traces, SQL or internal ids beyond the resource asked for.

## 5. Secrets and configuration

- All secrets from environment. `.env` ignored by git. `.env.example` lists names only.
- Production refuses to start if `JWT_SECRET` is short or equals the example, if `COOKIE_SECURE` is false, or if `CORS_ORIGINS` is empty.
- `JOB_TOKEN` (at least 32 random bytes) protects `/jobs/*`, compared with `hmac.compare_digest`. Rotated by changing the Render env var and the GitHub secret.
- Secrets never logged. A logging processor redacts keys named `password`, `token`, `authorization`, `api_key`, `secret`, `cookie`.
- GitHub Actions secrets: `DATABASE_URL`, `GEMINI_API_KEY`, `JOB_TOKEN`, `API_URL`. Never echoed.
- The Gemini key lives only on the backend and in the Actions job, never in the frontend bundle.

## 6. Audit

`audit_logs` is append only (trigger). Events:

`auth.login.success|failure`, `auth.lockout`, `auth.logout`, `auth.logout_all`, `auth.refresh_reuse`, `auth.password_change`, `settings.update`, `product.create|update|price_change|deactivate`, `supplier.update`, `terms.update`, `sale.create|void`, `return.create`, `po.create|send|cancel|close`, `receipt.post`, `adjustment.create`, `count.post`, `batch.write_off`, `decision.approve|edit|reject`, `report.generate|export`, `agent_action.confirm|reject`, `job.run`, `demo.reset`.

Each row stores `before` and `after` for updates (small diffs only), `request_id`, ip and user agent. Never store passwords, tokens or full request bodies.

## 7. Threat model summary

| Threat | Mitigation |
|---|---|
| Credential stuffing, brute force | argon2id, lockout, IP rate limit, generic errors, constant time path |
| Stolen access token | 15 minute life, memory only, CSP |
| Stolen refresh cookie | HttpOnly, rotation, reuse detection, family revocation, Secure, SameSite |
| XSS | React escaping, sanitized markdown, strict CSP, no `dangerouslySetInnerHTML` |
| CSRF | SameSite, custom header, Origin check, bearer for everything else |
| Cross tenant access | Four layers above plus tests |
| IDOR | Tenant scoped repositories, 404 not 403 for foreign ids |
| SQL injection | Parameterised queries only |
| Prompt injection | See `agents-spec.md` guardrails |
| Supabase Data API exposure | RLS deny all, revoked grants |
| Job endpoint abuse | Token auth, rate limit, idempotent runs |
| Dependency vulnerabilities | `pip-audit` and `npm audit` in CI (fail on high), Dependabot config |
| Log leakage | Redaction processor, no body logging |
| Cost abuse of LLM | Per user limits, caps, quota fallback |

## 8. Compliance notes (not legal advice)

- Synthetic personal data only. Owner names and emails are fictional. No customer personal data is stored (bills have no customer identity).
- India's Digital Personal Data Protection Rules, 2025 were notified in November 2025 with phased commencement. Before real customers: confirm applicability, document purposes, retention and deletion, rights handling.
- Pharmacy compliance (Drugs Rules, Schedule H1 records) is not claimed. Batch and expiry fields do not make the product compliant. Needs a separate review.
- GST: tax rate fields are informational. The product is not a filing tool.
- State all of this in the README limitations section and the Settings > About text.

## 9. Security checklist for every PR (self review in `progress.md`)

New endpoint has auth, role dependency, tenant scoping, validation, audit where needed, two-tenant test, rate limit if sensitive. No secret in diff. No new dependency without a reason in `memory.md`. Copy check passes.
