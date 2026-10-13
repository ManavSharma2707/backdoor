# Libraries

Use this file instead of searching the web for library usage. It lists what we use, why, the exact APIs to reach for, and the gotchas that waste time.

**Version policy.** Versions below are "major lines known good as of October 2026" from the planning session. Install the latest compatible release with the package manager, let `uv.lock` and `package-lock.json` pin it, and record exact versions under "Pinned versions" in `memory.md`. If an API here fails on the installed version, check `uv pip show <pkg>` or the package README locally, fix the usage, and update this file. Confirmed during planning: `langgraph` is on the 1.2.x line (1.2.1 released 21 May 2026, later patch versions exist).

Package managers: **uv** (Python), **npm** (Node 22 LTS). Python 3.12.

---

## 1. Backend

### Core web
| Package | Use | Key APIs and notes |
|---|---|---|
| `fastapi` | API | `FastAPI(lifespan=...)`, `APIRouter(prefix, tags, dependencies=[Depends(require_role("owner"))])`, `Depends`, `BackgroundTasks`, `Header`, `Response.set_cookie(key, value, httponly=True, secure=..., samesite="lax", path="/api/v1/auth", max_age=...)`. Define sync `def` endpoints (SQLAlchemy sync). Starlette runs them in a threadpool of 40 by default: set `anyio.to_thread.current_default_thread_limiter().total_tokens = 10` in lifespan to save memory on Render free |
| `uvicorn[standard]` | Server | Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'` with one worker. `--proxy-headers` makes client IPs correct behind Render for rate limits |
| `pydantic` v2, `pydantic-settings` | Schemas, config | List settings from a comma string need `Annotated[list[str], NoDecode]` plus a `field_validator(mode="before")`, otherwise pydantic-settings tries to parse JSON. A validator that raises a `RuntimeError` subclass (our `ConfigError`) is not wrapped in `ValidationError`, which gives a clearer startup failure. `BaseModel`, `Field(gt=0, max_length=...)`, `model_validator`, `ConfigDict(from_attributes=True)`, `field_serializer` for `Decimal` to str. `class Settings(BaseSettings): model_config = SettingsConfigDict(env_file=".env", extra="ignore")`. `Decimal` serialises to string in JSON mode by default, keep it |
| `email-validator` | `EmailStr` | `check_deliverability=False` (no DNS at runtime). Use a normal domain for seed emails (see `seed-data-spec.md`), special-use domains like `.test` and `.local` are rejected |
| `sse-starlette` | Chat stream | `EventSourceResponse(generator, ping=15)`. Generator yields `{"event": "token", "data": json.dumps(...)}`. Sync generators are supported (run in threadpool). Handle client disconnect by catching `asyncio.CancelledError` or checking `request.is_disconnected()` |
| `slowapi` | Rate limits | `limiter = Limiter(key_func=get_remote_address)`, `app.state.limiter = limiter`, `app.add_exception_handler(RateLimitExceeded, handler)`, `@limiter.limit("10/minute")` and the endpoint must take `request: Request`. In-memory store, fine for one instance |
| `structlog` | Logging | JSON renderer, `contextvars` for `request_id`, `tenant_id`. Add a redaction processor for sensitive keys. To put stdlib loggers (uvicorn, alembic, sqlalchemy) through the same pipeline use `structlog.stdlib.ProcessorFormatter` on one root handler, with `foreign_pre_chain` set to the shared processors. See `app/core/logging.py` |
| `tenacity` | Retries | `@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(1, 8), retry=retry_if_exception_type(...))` for Gemini calls |
| `cachetools` | In-process TTL cache | `TTLCache(maxsize=256, ttl=300)` with a lock |
| `python-dateutil` | Date math | `relativedelta`. `zoneinfo` (stdlib) for IST, add `tzdata` package for slim images |

### Database
| Package | Use | Key APIs and notes |
|---|---|---|
| `sqlalchemy` 2.0 | ORM and Core | Typed models: `class Base(DeclarativeBase)`, `Mapped[int]`, `mapped_column(...)`. Queries: `select(Model).where(...)`, `session.execute(stmt).scalars()`. Naming convention (composite aware, `D-043`): `MetaData(naming_convention={"ix": "ix_%(table_name)s_%(column_0_N_name)s", "uq": "uq_%(table_name)s_%(column_0_N_name)s", "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"})`. Long generated names are shortened with a hash by SQLAlchemy, which is fine. Give every `CheckConstraint` and `Index` an explicit name. Descending index columns: `Index("ix_x", "tenant_id", desc("as_of_date"))`. `postgresql_nulls_not_distinct=True` works on both `UniqueConstraint` and `Index`, and Alembic round trips it. `sort_order=` on `mapped_column` keeps mixin columns (`id`, `tenant_id`, `created_at`) in a readable position. SQLAlchemy resolved to 2.1.x, which passes the whole suite. Composite FK: `ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"])`. Partial index: `Index("ix_x", "col", unique=True, postgresql_where=text("is_primary AND effective_to IS NULL"))`. Nulls not distinct unique: `UniqueConstraint("tenant_id", "product_id", "batch_id", postgresql_nulls_not_distinct=True)`. Generated columns: `Computed("counted_qty - system_qty", persisted=True)`. Types: `postgresql.UUID(as_uuid=True)`, `ARRAY`, `JSONB`, `INET`, `CITEXT` (`sqlalchemy.dialects.postgresql.CITEXT`), `Numeric(14, 3)`. Upserts: `from sqlalchemy.dialects.postgresql import insert` then `.on_conflict_do_update(index_elements=[...], set_={...})`. Row locks: `.with_for_update()` and order by key |
| `psycopg[binary,pool]` v3 | Driver | URL `postgresql+psycopg://user:pass@host:5432/db`. Engine: `create_engine(url, pool_size=5, max_overflow=2, pool_pre_ping=True, pool_recycle=1800)`. With a transaction pooler (port 6543) add `connect_args={"prepare_threshold": None}`. Use the **session pooler** (port 5432 on the pooler host) by default, see `deployment.md`. Bulk load: `with cur.copy("COPY sale_lines (col1, col2) FROM STDIN") as copy: copy.write_row(row)` |
| `alembic` | Migrations | Programmatic use: `Config("alembic.ini")`, set `script_location` to an absolute path, pass the URL through `config.attributes["database_url"]` and set `config.attributes["configure_logger"] = False`, otherwise `fileConfig` in `env.py` replaces the application logging. Add `known-third-party = ["alembic"]` to ruff isort, because the local `alembic/` folder makes ruff think it is first party. `command.check(config)` raises when the models and the database differ. `alembic.ini` needs `path_separator = os`. `env.py`: import `Base.metadata`, set `compare_type=True`, `include_object` function that skips tables named `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`. Hand write migrations for extensions, triggers, views, RLS, generated columns and nulls-not-distinct (autogenerate misses some). `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`. Run `alembic upgrade head` in `start.sh` under `pg_advisory_lock` |
| `pgvector` (python) | Vector type | `from pgvector.sqlalchemy import Vector`, column `Vector(768)`, distance `Model.embedding.cosine_distance(q)`. Register nothing extra with psycopg3 when using SQLAlchemy type, otherwise `register_vector(conn)` |

Local Postgres image: `pgvector/pgvector:pg16` (PostgreSQL 16.15 with pgvector 0.8.7 when checked on 2026-10-13). Supabase: enable `vector`, `citext`, `pg_trgm` from the dashboard or migration (extensions live in the `extensions` schema which is on the default `search_path`).

### Security
| Package | Use | Key APIs and notes |
|---|---|---|
| `PyJWT` | Access tokens | `jwt.encode(payload, secret, algorithm="HS256")`. `jwt.decode(token, secret, algorithms=["HS256"], audience="backroom-web", issuer="backroom", options={"require": ["exp", "iat", "nbf", "sub"]}, leeway=10)`. Catch `jwt.InvalidTokenError`. Do not use `python-jose` (unmaintained) |
| `argon2-cffi` | Password hashing | `ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)`. `ph.hash(pw)`, `ph.verify(hash, pw)` raises `VerifyMismatchError`, `ph.check_needs_rehash(hash)`. Verify a dummy hash for unknown emails to equalise timing |
| stdlib `secrets`, `hashlib`, `hmac` | Refresh tokens, job token | `secrets.token_urlsafe(32)`, `hashlib.sha256(tok.encode()).hexdigest()`, `hmac.compare_digest` |

### Data and ML
| Package | Use | Key APIs and notes |
|---|---|---|
| `numpy` | Math | Vectorise. Generators: `np.random.Generator(np.random.PCG64(seed))`, `rng.negative_binomial`, `rng.poisson`, `rng.lognormal`. Use `float32` for big arrays |
| `pandas` | Aggregation, features | `groupby`, `pivot`, `rolling`, `shift`. Pandas 3 changes defaults (string dtype, copy-on-write): avoid chained assignment, use `.loc`. Read from DB with `pd.read_sql(text, engine, params=...)` or build frames from `result.mappings()`. Do not load all history for all tenants at once |
| `scikit-learn` | Metrics, fallback model | `mean_absolute_error`, `mean_squared_error`. Fallback: `HistGradientBoostingRegressor(loss="poisson")` if LightGBM cannot be imported. Rolling origin backtest is custom (not `TimeSeriesSplit`) |
| `lightgbm` | Global demand model | `lgb.LGBMRegressor(objective="tweedie", tweedie_variance_power=1.2, n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=50, colsample_bytree=0.8, subsample=0.8, subsample_freq=1, n_jobs=1, random_state=42, verbose=-1)`. Pass `categorical_feature=["category_code"]` with integer codes. **Docker slim images need `apt-get install -y libgomp1`**. Import lazily inside functions so the API process does not pay the import cost. Predictions can be slightly negative: clip at 0 |
| `scipy` | Not used | Use `statistics.NormalDist().cdf/inv_cdf/pdf` |
| `statsmodels` | Not used | Own numpy SES and Croston (small, testable) |
| `PyYAML` | Catalog files | `yaml.safe_load` only |
| `Faker` | Names and phones for seed | `Faker("en_IN")`, `fake.seed_instance(seed)`. Only for contact people and phone patterns, never for products |

### Exports
| Package | Use | Key APIs and notes |
|---|---|---|
| `reportlab` | PDF | `SimpleDocTemplate(buf, pagesize=A4, leftMargin=16*mm, ...)`, `Table(data, colWidths, repeatRows=1)`, `TableStyle([...])`, `Paragraph(text, style)` with `wordWrap`, `KeepTogether`, `PageBreak`. Header and footer via `doc.build(story, onFirstPage=fn, onLaterPages=fn)` drawing on the canvas (`canvas.drawString`, page number `canvas.getPageNumber()`; for "of m" use a `NumberedCanvas` subclass). Fonts: `pdfmetrics.registerFont(TTFont("Plex", "IBMPlexSans-Regular.ttf"))`, Medium and SemiBold likewise, `registerFontFamily`. The Rupee sign (U+20B9) is missing from the built-in Helvetica, so the TTF is mandatory. Charts: `reportlab.graphics.shapes` (Drawing, Rect, String) for a simple budget bar, no matplotlib |
| `XlsxWriter` | Excel | `wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})`, `ws.write_string`, `ws.write_number`, `ws.write_formula("H2", "=F2*G2", fmt, value=precomputed)` (pass the value so viewers that do not recalculate still show numbers), `ws.freeze_panes(1, 0)`, `ws.autofilter(0, 0, last_row, last_col)`, `ws.set_column("A:A", 28)`, `wb.add_format({"num_format": "[$₹-4009]#,##0.00", "bold": True, "bg_color": "#F5F3EE", "bottom": 1})`, `ws.write_comment`. Write only, no read. Tests read with `openpyxl` (dev dependency) |
| stdlib `csv` | CSV | `io.StringIO`, `csv.writer(f)`, encode result with `utf-8-sig` |

### AI
| Package | Use | Key APIs and notes |
|---|---|---|
| `google-genai` | Embeddings, model listing | `client = genai.Client(api_key=...)`. List: `client.models.list()`. Embed: `client.models.embed_content(model=EMBED_MODEL, contents=[...], config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=768))`, vectors at `resp.embeddings[i].values`. **L2 normalise** after truncation. Batch up to 100 inputs, respect rate limits |
| `langchain-core` | Messages, tools, runnables | `@tool(args_schema=Model)`, `AIMessage`, `ToolMessage`, `SystemMessage`, `HumanMessage`, `RunnableConfig`. Text of an AIMessage can be a string or a list of blocks (thinking models): write one helper `message_text(msg)` that handles both |
| `langchain-google-genai` | Gemini chat model | `ChatGoogleGenerativeAI(model=..., temperature=0, max_retries=2, timeout=40, google_api_key=...)`, `.bind_tools(tools)`, `.with_structured_output(PydanticModel)`, `.invoke(messages)`. Gemini needs the first message to be from the user (after system), and every tool call needs a matching `ToolMessage`. Keep tool schemas flat with simple types for best function calling |
| `langgraph` | Orchestration | `StateGraph(AgentState)`, `graph.add_node(name, fn)`, `add_edge`, `add_conditional_edges(node, router_fn, mapping)`, `START`, `END`, `graph.compile(checkpointer=saver)`, `ToolNode(tools)` or a custom tool node, `interrupt(value)` inside a node and resume with `graph.invoke(Command(resume=...), config)`, config `{"configurable": {"thread_id": "..."}}`, `graph.stream(input, config, stream_mode=["updates", "custom"])`, custom events via `get_stream_writer()`. Reducer: `Annotated[list, add_messages]` |
| `langgraph-checkpoint-postgres` | Persistence | `from langgraph.checkpoint.postgres import PostgresSaver`, `from psycopg_pool import ConnectionPool`, `pool = ConnectionPool(conninfo, max_size=3, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})`, `saver = PostgresSaver(pool)`, `saver.setup()` once. Must be the psycopg3 stack (not psycopg2) |
| `psycopg-pool` | Pool for the checkpointer | Included with `psycopg[pool]` |

Do not install the `langchain` meta package, `langchain-community`, or `langsmith` tracing (memory and noise). Disable telemetry env `LANGCHAIN_TRACING_V2=false`.

### Dev and quality
The project is an application, not a package: `[tool.uv] package = false`, so `uv run` never builds or reinstalls it and code is imported from the working directory (`pythonpath = ["."]` for pytest). Python 3.12 syntax is used (`class Repo[T: Base]`, `def f[T](...)`). On a synced folder such as OneDrive keep the virtualenv outside it with `UV_PROJECT_ENVIRONMENT`, otherwise file locks break `uv sync`. `uv run --directory backend ...` runs a command from the repo root.

`pytest`, `pytest-cov`, `hypothesis` (property tests for ledger and engine), `httpx` (TestClient transport), `openpyxl` (read xlsx in tests), `pypdf` (extract PDF text in tests), `ruff` (lint and format), `mypy`, `pre-commit`, `pip-audit`, `types-PyYAML`.

Test database: compose service `db`, a separate database `backroom_test` (the name must end in `_test`, the fixture refuses anything else), the public schema is dropped and rebuilt with the real migrations once per session, each test is wrapped in a transaction that is rolled back (`connection.begin()`, session bound to it with `join_transaction_mode="create_savepoint"`). Expected database errors are asserted with the `rejected(db, exc, match)` helper in `tests/conftest.py`, which runs the block in a savepoint so the test transaction survives. Tests that run migrations use `scratch_database(url, name)`.

---

## 2. Frontend

Node 22 LTS, npm, Vite, TypeScript strict.

| Package | Use | Key APIs and notes |
|---|---|---|
| `react`, `react-dom` 19 | UI | Function components, hooks only. `StrictMode` on |
| `vite`, `@vitejs/plugin-react` | Build | `server.proxy: {"/api": "http://localhost:8000"}` in dev. `build.sourcemap: false` in prod. Env via `import.meta.env.VITE_*` |
| `typescript` | Types | `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` off |
| `tailwindcss` v4, `@tailwindcss/vite` | Styling | `@import "tailwindcss";` in CSS, tokens in `@theme { --color-bg: #F5F3EE; ... }` which generate utilities like `bg-bg`. No `tailwind.config.js` needed. Arbitrary values only if a token is missing (then add the token) |
| `radix-ui` | Accessible primitives | Dialog, Popover, Tooltip, Tabs, Select, DropdownMenu, Checkbox, RadioGroup, Switch, Toast not used (sonner). Wrap each in our own component in `components/ui/` styled with tokens. Copy patterns from shadcn/ui if helpful but **do not keep its default look** |
| `class-variance-authority`, `clsx`, `tailwind-merge` | Variants | `cva` for Button and Badge variants, `cn = (...a) => twMerge(clsx(a))` |
| `react-router` v7 | Routing | `createBrowserRouter([...])`, `RouterProvider`, `Outlet`, `useSearchParams` for filters, `Navigate`, `useNavigate`. Guard routes with a `RequireAuth` layout component |
| `@tanstack/react-query` v5 | Server state | `useQuery({ queryKey: ["products", filters], queryFn, placeholderData: keepPreviousData })`, `useMutation({ mutationFn, onSuccess: () => qc.invalidateQueries({ queryKey: [...] }) })`. Defaults: `staleTime 30_000`, `retry 1`, no refetch on window focus for report pages |
| `@tanstack/react-table` v8 | Tables | `useReactTable({ data, columns, getCoreRowModel: getCoreRowModel(), manualPagination: true, manualSorting: true })`. Server side sorting and paging. Column defs typed. Right align numeric columns, sticky header via CSS |
| `react-hook-form`, `@hookform/resolvers`, `zod` | Forms | `useForm({ resolver: zodResolver(schema) })`. Check the installed zod major (v4 moved some helpers like `z.email()`). Show errors on blur |
| `recharts` v3 | Charts | `ResponsiveContainer`, `LineChart`, `BarChart`, `XAxis`, `YAxis`, `CartesianGrid` (horizontal only), `Tooltip` with custom content, `ReferenceArea` for festival bands, `Line` with `dot={false}`, `strokeWidth={2}`. Colors from tokens. Add `accessibilityLayer` and a text summary next to each chart |
| `lucide-react` | Icons | Stroke 1.5, size 16 or 18. Never use the sparkles or wand icons for the assistant |
| `sonner` | Toasts | `toast.success(copy.sale.saved)`. Position bottom right, no icons beyond default, durations 4 s |
| `cmdk` | Command palette | Ctrl or Cmd K opens product and page search |
| `date-fns` v4 | Dates | `format(date, "d MMM yyyy")`, `parseISO`, `addDays`. IST display uses `Intl.DateTimeFormat("en-IN", {timeZone: "Asia/Kolkata"})` |
| `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono` | Fonts | `import "@fontsource/ibm-plex-sans/400.css"` plus 500 and 600, mono 400 and 500. Self hosted for CSP and speed |
| `@microsoft/fetch-event-source` | SSE with POST and headers | `fetchEventSource(url, { method: "POST", headers, body, signal, openWhenHidden: true, onmessage(ev) { ... }, onerror(err) { throw err } })`. Native `EventSource` cannot send POST or auth headers |
| `react-markdown`, `remark-gfm`, `rehype-sanitize` | Chat text | No raw HTML. Custom `components` for `a` (safe rel) and `p`. Keep markdown minimal, the assistant rarely uses it |
| `openapi-typescript` (dev) | API types | `npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.d.ts` (script `make openapi-types`). Types only, we use our own fetch wrapper |
| `vitest`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`, `msw` v2 | Tests | `render`, `screen`, `userEvent.setup()`. MSW: `http.get("/api/v1/...", () => HttpResponse.json(...))` with `setupServer` |
| `@playwright/test` | E2E | Login, plan, approve, export. Use the seeded demo accounts against a local stack |
| `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-jsx-a11y`, `prettier` | Lint | `jsx-a11y` recommended on. Plus the copy check script |

Formatting helpers (`lib/format.ts`), all built on `Intl`:
```ts
const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });
const qty  = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });
export const money = (s: string, dp: 0 | 2 = 0) => (dp === 0 ? inr0 : inr2).format(Number(s));
```
`en-IN` groups as 1,82,340 automatically. Compact lakh and crore for KPI cards: implement `compactInr` (under 1 lakh show full, 1 lakh to under 1 crore show "1.8 lakh", above show "1.2 crore").

---

## 3. Tooling and infrastructure

| Tool | Use | Notes |
|---|---|---|
| Docker and Compose v2 | Local stack | Services `db` (`pgvector/pgvector:pg16`, volume, healthcheck `pg_isready`), `api` (build `./backend`, mounts source for reload in dev, depends_on db healthy), `web` (node 22, `npm run dev -- --host`) |
| Backend Dockerfile | Image | The virtualenv lives in `/opt/venv` (`UV_PROJECT_ENVIRONMENT`), not `/app/.venv`, because compose bind mounts `./backend` over `/app` and would hide it. `FROM python:3.12-slim`, `apt-get install -y --no-install-recommends libgomp1 libpq5 curl`, copy `uv` binary from `ghcr.io/astral-sh/uv`, `uv sync --frozen --no-dev`, non-root user, `HEALTHCHECK curl -f http://localhost:$PORT/api/v1/health`, `CMD ["./start.sh"]`. Multi stage to keep the image small |
| `start.sh` | Boot | Run migrations with advisory lock, then `exec uvicorn ...` |
| GitHub Actions | CI and scheduler | `actions/checkout`, `astral-sh/setup-uv`, `actions/setup-node`, service container `pgvector/pgvector:pg16` with health options. Scheduled workflow with `cron` in UTC and `workflow_dispatch` |
| Render | API host | Blueprint `render.yaml`, Docker runtime, free plan, `healthCheckPath`, env vars `sync: false` for secrets |
| Vercel | Frontend host | `vercel.json` rewrites and headers, framework preset Vite, build `npm run build`, output `dist` |
| Supabase | Postgres | Session pooler connection string, extensions, RLS |

## 4. Things we deliberately do not use

Celery or Redis (no queue), microservices, GraphQL, ORMs on the frontend, Redux, CSS-in-JS, Material UI or Chakra (they impose a generic look), Axios (fetch is enough), moment.js, matplotlib, statsmodels, Prophet, scipy, langchain meta package, vector database services (pgvector is enough), Supabase client libraries and Supabase Auth (we own auth), PostgREST usage.

## 5. Adding a library

Add a row here with the reason, record the version in `memory.md`, and check it against the memory budget (`deployment.md`). Prefer standard library or existing dependencies first.
