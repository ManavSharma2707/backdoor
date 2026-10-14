# Database

PostgreSQL 15 or newer (local: `pgvector/pgvector:pg16`, Supabase: 15+). Extensions: `pgcrypto` (or built-in `gen_random_uuid`), `citext`, `pg_trgm`, `vector`, `btree_gist` (only if exclusion constraints are added later).

The database is the system of record. Normalised to third normal form, with three deliberate exceptions, all labelled: cached counters (`stock_balances`, `purchase_order_lines.quantity_received`, `sale_lines.returned_qty`), the derived feature table `daily_product_stats`, and snapshot JSON on reports.

---

## 1. Conventions

| Topic | Rule |
|---|---|
| Names | `snake_case`, plural table names, singular column names. Constraint names via SQLAlchemy `naming_convention`: `pk_`, `fk_`, `uq_`, `ix_`, `ck_` prefixes. The `fk`, `uq` and `ix` patterns use `column_0_N_name` (all columns, underscore joined) because almost every constraint starts with `tenant_id`. Every `Index` and `CheckConstraint` is given an explicit name (`D-043`) |
| Primary keys | `id uuid default gen_random_uuid()` everywhere, except bigint identity for high volume append-only tables: `sale_lines`, `inventory_movements`, `forecast_values`, `audit_logs`, `agent_steps`. Composite PK for `daily_product_stats`, `synthetic_true_demand`, `business_settings` (PK = `tenant_id`) |
| Tenancy | Every tenant-owned table has `tenant_id uuid not null references tenants(id)`. Parents expose `UNIQUE (tenant_id, id)`. **Every intra-tenant foreign key is composite** `(tenant_id, parent_id) -> parent(tenant_id, id)` so a row can never point at another tenant's data. `created_by` / `user_id` columns are plain FKs to `users(id)` |
| Enums | `text` with `CHECK (col IN (...))`. No native enum types (easier migrations) |
| Money | `NUMERIC(14,2)` for amounts, `NUMERIC(12,4)` for unit prices and costs. Never float |
| Quantity | `NUMERIC(14,3)`. Base unit is the sellable pack (strip, bottle, pack, kg) |
| Time | `timestamptz` UTC for instants. `date` for business dates in `Asia/Kolkata` |
| Soft state | `is_active` on products, suppliers, categories, users. Transactions are voided with a status, never deleted |
| Timestamps | `created_at timestamptz not null default now()`. `updated_at` on mutable tables, maintained by a trigger `set_updated_at()` |
| JSON | `jsonb` only for snapshots, evidence and config blobs. Anything queried or joined is a real column |
| Nullable batch | `UNIQUE NULLS NOT DISTINCT` (PG15+) where batch id may be null |
| RLS | Enabled on every table with **no policies** (deny all through the Supabase Data API). The backend connects as the owner role, which bypasses RLS. `REVOKE ALL ... FROM anon, authenticated` on all tables and the schema usage |

SQLAlchemy helper: define `TenantMixin` (tenant_id) and `composite_fk(parent_table, cols)` in `models/base.py`. Cross-tenant insert tests are mandatory.

---

## 2. Tables

Notation: `col type [null] [default] - note`. `PK`, `UQ`, `FK` marked. All columns `not null` unless marked `null`.

### 2.1 Reference (global, no tenant)

**tax_rates**: `id PK`, `code text UQ` (`GST0`, `GST5`, `GST18`, `GST40`), `rate_pct numeric(5,2)`, `label text`, `effective_from date`, `effective_to date null`, `notes text null`. Seeded with the post 22 Sep 2025 structure (0, 5, 18, 40). Verify before treating as authoritative.

**calendar_events**: `id PK`, `slug text UQ` (e.g. `diwali-2026`), `event_key text` (groups yearly occurrences, e.g. `diwali`), `name text`, `kind text` (`festival|season|holiday`), `start_date date`, `end_date date`, `pre_window_days smallint default 7`, `post_window_days smallint default 3`, `delivery_delay_days smallint default 0`, `affects_hours boolean default false`, `region_scope text default 'maharashtra'`, `is_verified boolean default false`, `is_active boolean default true`, `source_note text null`, `created_at`. `CHECK end_date >= start_date`. `UQ (event_key, start_date)`.

**model_versions**: `id PK`, `name text`, `version text`, `git_sha text null`, `notes text null`, `created_at`. `UQ (name, version)`. Row per engine release (`forecast-engine`, `replenishment-engine`).

### 2.2 Tenancy and auth

**tenants**: `id PK`, `slug text UQ`, `name text`, `business_type text` (`fmcg|medical`), `profile_key text null`, `timezone text default 'Asia/Kolkata'`, `currency char(3) default 'INR'`, `is_synthetic boolean default false`, `is_active boolean default true`, `created_at`, `updated_at`.

**users**: `id PK`, `tenant_id FK`, `email citext UQ` (global), `password_hash text`, `full_name text`, `role text default 'owner'` (`owner|manager|staff`), `is_active boolean default true`, `failed_login_count int default 0`, `locked_until timestamptz null`, `last_login_at timestamptz null`, `last_failed_login_at timestamptz null` (added in `0011`, time of the latest failure, for the 15 minute window), `password_changed_at timestamptz`, `created_at`, `updated_at`. `UQ (tenant_id, id)`.

**refresh_tokens**: `id PK`, `tenant_id`, `user_id` (composite FK to users), `family_id uuid`, `token_hash char(64) UQ` (SHA-256 of the opaque token), `issued_at`, `expires_at`, `last_used_at null`, `rotated_at null`, `revoked_at null`, `revoked_reason text null` (`logout|logout_all|reuse_detected|password_change|expired`), `replaced_by_id uuid null`, `user_agent text null`, `ip inet null`. Indexes: `(user_id)`, `(family_id)`, `(expires_at)`.

**business_settings** (PK `tenant_id`): `weekly_budget numeric(14,2) null`, `service_level numeric(4,3) default 0.95`, `review_period_days smallint default 7`, `default_lead_time_days smallint default 3`, `near_expiry_days smallint default 90`, `nonmoving_days smallint default 60`, `slow_cover_days smallint default 90`, `excess_horizon_days smallint default 30`, `forecast_horizon_days smallint default 28`, `backtest_origins smallint default 12`, `stale_count_days smallint default 30`, `sellable_shelf_life_fraction numeric(3,2) default 0.60`, `censor_policy text default 'exclude'` (`exclude|weekday_fill`), `pack_rounding text default 'up'` (`up|nearest_safe`), `priority_weights jsonb` (default `{"risk":0.45,"value":0.30,"confidence":0.15,"excess":0.10}`), `apply_festival_lead_padding boolean default true`, `agents_enabled boolean default true`, `updated_at`.

### 2.3 Catalogue

**categories**: `id PK`, `tenant_id`, `parent_id uuid null` (composite FK self), `name`, `slug`, `position smallint default 0`, `is_active`. `UQ (tenant_id, slug)`, `UQ (tenant_id, id)`.

**products**: `id PK`, `tenant_id`, `sku text`, `barcode text null`, `name text`, `brand text null`, `category_id` (composite FK), `base_unit text` (`pcs|pack|strip|bottle|tube|sachet|box|kg|litre|vial|tin`), `pack_label text null` (e.g. `100 g`, `10 tablets`), `tax_rate_id` FK, `mrp numeric(12,2)`, `selling_price numeric(12,2)`, `is_batch_tracked boolean default false`, `shelf_life_days int null`, `schedule_class text null` (`H|H1|X`, flag only), `generic_name text null`, `strength text null`, `dosage_form text null`, `manufacturer text null`, `min_stock_qty numeric(14,3) default 0`, `is_seasonal boolean default false`, `launched_on date null`, `is_active boolean default true`, `notes text null`, `created_at`, `updated_at`. `UQ (tenant_id, sku)`, `UQ (tenant_id, id)`. `CHECK selling_price >= 0 AND mrp >= 0`. Indexes: `(tenant_id, category_id)`, GIN trigram on `name`, `sku`, `brand`, `generic_name`. Schedule class is informational only and never drives logic.

**product_prices**: `id PK`, `tenant_id`, `product_id`, `mrp`, `selling_price`, `effective_from date`, `effective_to date null`, `reason text null`. `UQ (tenant_id, product_id, effective_from)`.

**product_equivalents**: `id PK`, `tenant_id`, `product_id`, `equivalent_product_id`, `note text null`, `created_by`, `created_at`. `UQ (tenant_id, product_id, equivalent_product_id)`. `CHECK product_id <> equivalent_product_id`. Retailer defined only.

**suppliers**: `id PK`, `tenant_id`, `code text`, `name text`, `contact_name text null`, `phone text null`, `email text null`, `payment_terms_days smallint default 0`, `default_lead_time_days smallint null`, `delivery_weekdays smallint[] null` (ISO 1 to 7), `min_order_value numeric(14,2) null`, `credit_limit numeric(14,2) null`, `accepts_expiry_returns boolean default false`, `expiry_return_window_days smallint null` (days before or after expiry within which returns are accepted), `return_window_days smallint null`, `is_active`, `notes text null`, `created_at`, `updated_at`. `UQ (tenant_id, code)`, `UQ (tenant_id, id)`.

**supplier_product_terms**: `id PK`, `tenant_id`, `supplier_id`, `product_id` (composite FKs), `is_primary boolean default false`, `purchase_price numeric(12,4)`, `pack_size numeric(14,3) default 1`, `moq_units numeric(14,3) default 0`, `lead_time_days smallint null`, `effective_from date`, `effective_to date null`, `created_at`. `CHECK pack_size > 0`. `UQ (tenant_id, supplier_id, product_id, effective_from)`. Partial unique index: `UNIQUE (tenant_id, product_id) WHERE is_primary AND effective_to IS NULL`.

### 2.4 Sales

**promotions**: `id PK`, `tenant_id`, `name`, `kind text` (`discount|bundle|bogo|festival_offer`), `product_id null`, `category_id null`, `discount_pct numeric(5,2)`, `starts_on date`, `ends_on date`, `created_by null`, `created_at`. `CHECK (product_id IS NULL) <> (category_id IS NULL)`, `CHECK ends_on >= starts_on`.

**sales**: `id PK`, `tenant_id`, `bill_no text`, `business_date date`, `sold_at timestamptz`, `payment_mode text` (`cash|upi|card|credit`), `status text default 'completed'` (`completed|void`), `subtotal numeric(14,2)`, `discount_total numeric(14,2) default 0`, `tax_total numeric(14,2) default 0`, `total numeric(14,2)`, `idempotency_key text null`, `void_reason text null`, `voided_at timestamptz null`, `voided_by uuid null`, `source text default 'app'` (`app|seed|import`), `created_by null`, `created_at`. `UQ (tenant_id, bill_no)`, `UQ (tenant_id, id)`, partial `UQ (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL`. Index `(tenant_id, business_date)`.

**sale_lines**: `id bigint identity PK`, `tenant_id`, `sale_id` (composite FK), `product_id`, `batch_id null` (composite FKs), `quantity numeric(14,3)`, `unit_price numeric(12,4)`, `discount_amount numeric(14,2) default 0`, `tax_rate_pct numeric(5,2)`, `line_total numeric(14,2)`, `promotion_id null`, `returned_qty numeric(14,3) default 0` (cache), `business_date date` (denormalised copy for index), `created_at`. `CHECK quantity > 0`, `CHECK returned_qty <= quantity`. `UQ (tenant_id, id)`. Indexes `(tenant_id, product_id, business_date)`, `(tenant_id, sale_id)`.

**sale_returns**: `id PK`, `tenant_id`, `sale_id`, `return_no text`, `business_date date`, `reason text`, `status text default 'posted'` (`posted|void`), `refund_total numeric(14,2)`, `created_by null`, `created_at`. `UQ (tenant_id, return_no)`, `UQ (tenant_id, id)`.

**sale_return_lines**: `id bigint identity PK`, `tenant_id`, `return_id`, `sale_line_id` (composite FK to `sale_lines(tenant_id,id)`), `product_id`, `batch_id null`, `quantity numeric(14,3)`, `refund_amount numeric(14,2)`, `disposition text` (`restock|damaged|expired`). `CHECK quantity > 0`.

### 2.5 Purchasing

**purchase_orders**: `id PK`, `tenant_id`, `supplier_id`, `po_number text`, `status text default 'draft'` (`draft|sent|partially_received|received|cancelled|closed`), `order_date date`, `expected_date date null`, `sent_at null`, `cancelled_at null`, `cancel_reason text null`, `subtotal_estimated numeric(14,2) default 0`, `source text default 'manual'` (`manual|recommendation|seed`), `recommendation_run_id uuid null`, `notes text null`, `created_by null`, `created_at`, `updated_at`. `UQ (tenant_id, po_number)`, `UQ (tenant_id, id)`. Index `(tenant_id, status, expected_date)`.

**purchase_order_lines**: `id PK`, `tenant_id`, `po_id`, `product_id`, `quantity_ordered numeric(14,3)`, `unit_cost numeric(12,4)`, `pack_size numeric(14,3)`, `quantity_received numeric(14,3) default 0` (cache), `recommendation_line_id uuid null`, `created_at`. `CHECK quantity_ordered > 0`. `UQ (tenant_id, po_id, product_id)`, `UQ (tenant_id, id)`.

**goods_receipts**: `id PK`, `tenant_id`, `supplier_id`, `purchase_order_id null`, `receipt_no text`, `received_on date`, `invoice_no text null`, `invoice_total numeric(14,2) null`, `status text default 'posted'` (`posted|void`), `is_exception boolean default false`, `exception_note text null`, `idempotency_key text null`, `created_by null`, `created_at`. `CHECK (NOT is_exception OR exception_note IS NOT NULL)`. `UQ (tenant_id, receipt_no)`, `UQ (tenant_id, id)`.

**receipt_lines**: `id PK`, `tenant_id`, `receipt_id`, `po_line_id null`, `product_id`, `batch_id null`, `quantity_received numeric(14,3)`, `unit_cost numeric(12,4)`, `mrp numeric(12,2) null`, `created_at`. `CHECK quantity_received > 0`.

### 2.6 Inventory

**product_batches**: `id PK`, `tenant_id`, `product_id`, `batch_no text`, `expiry_date date`, `manufactured_on date null`, `mrp numeric(12,2) null`, `unit_cost numeric(12,4)`, `received_on date`, `initial_qty numeric(14,3)`, `status text default 'active'` (`active|quarantined|expired|closed`), `created_at`. `UQ (tenant_id, product_id, batch_no)`, `UQ (tenant_id, id)`. Index `(tenant_id, expiry_date)`.

**inventory_movements**: `id bigint identity PK`, `tenant_id`, `product_id`, `batch_id null` (composite FKs), `movement_type text` (`opening|receipt|sale|void_reversal|return_in|damage|expiry_writeoff|supplier_return|adjustment|count_correction`), `quantity_delta numeric(14,3)` (signed, `CHECK <> 0`), `unit_cost numeric(12,4) null`, `occurred_at timestamptz`, `business_date date`, `source_type text` (`sale|sale_return|receipt|adjustment|stock_count|opening|void`), `source_id text` (uuid or bigint as text), `reason_code text null`, `note text null`, `reverses_movement_id bigint null`, `created_by null`, `created_at`. Indexes `(tenant_id, product_id, business_date)`, `(tenant_id, source_type, source_id)`, `(tenant_id, batch_id)`.

**stock_balances**: `id PK`, `tenant_id`, `product_id`, `batch_id null`, `on_hand numeric(14,3) default 0`, `reserved_qty numeric(14,3) default 0`, `avg_unit_cost numeric(12,4) default 0`, `last_movement_at timestamptz null`, `updated_at`. `CHECK on_hand >= 0`. `UQ NULLS NOT DISTINCT (tenant_id, product_id, batch_id)`. Index `(tenant_id, product_id)`. A reserved quantity source does not exist in the MVP, the column feeds the formula and defaults to 0.

**stock_counts**: `id PK`, `tenant_id`, `count_date date`, `status text default 'draft'` (`draft|posted|void`), `note text null`, `created_by null`, `posted_at null`, `created_at`. `UQ (tenant_id, id)`.

**stock_count_lines**: `id PK`, `tenant_id`, `count_id`, `product_id`, `batch_id null`, `system_qty numeric(14,3)`, `counted_qty numeric(14,3) null` (null until counted, nullable since `0011`), `variance numeric(14,3) null GENERATED ALWAYS AS (counted_qty - system_qty) STORED`. `UQ NULLS NOT DISTINCT (tenant_id, count_id, product_id, batch_id)`.

**stock_adjustments**: `id PK`, `tenant_id`, `product_id`, `batch_id null`, `quantity_delta numeric(14,3)`, `reason_code text` (`damage|expiry_writeoff|theft_loss|found|correction|supplier_return|other`), `note text null`, `business_date date`, `movement_id bigint`, `idempotency_key text null`, `created_by null`, `created_at`. `CHECK quantity_delta <> 0`.

**stockout_intervals**: `id PK`, `tenant_id`, `product_id`, `start_date date`, `end_date date null` (open interval), `source text` (`recorded|inferred`), `note text null`, `created_by null`, `created_at`. `CHECK end_date IS NULL OR end_date >= start_date`. `UQ (tenant_id, product_id, start_date, source)`.

### 2.7 Derived data (rebuildable)

**daily_product_stats**: PK `(tenant_id, product_id, stat_date)`. `units_sold numeric(14,3)`, `units_returned numeric(14,3)` (restocked returns), `revenue numeric(14,2)`, `avg_price numeric(12,4) null`, `opening_on_hand numeric(14,3)`, `closing_on_hand numeric(14,3)`, `receipts_qty numeric(14,3)`, `availability_state text` (`available|stocked_out_all_day|sold_out_during_day|not_launched|unknown`), `is_censored boolean`, `promo_active boolean`, `event_keys text[]`, `updated_at`. Index `(tenant_id, stat_date)`. Demand used by models: `units_sold - units_returned` on trusted days.

**synthetic_true_demand**: PK `(tenant_id, product_id, stat_date)`. `true_demand numeric(14,3)`, `event_multiplier numeric(6,3) null`, `promo_multiplier numeric(6,3) null`. Seed only. Read only by evaluation scripts, never by product code paths.

### 2.8 Intelligence

**forecast_runs**: `id PK`, `tenant_id`, `kind text` (`weekly|backtest|adhoc`), `profile text` (`light|full`), `data_cutoff timestamptz`, `as_of_date date`, `horizon_days smallint`, `model_version_id` FK, `config jsonb`, `status text` (`running|succeeded|failed`), `started_at`, `finished_at null`, `error text null`. `UQ (tenant_id, id)`. Index `(tenant_id, as_of_date desc)`.

**forecast_values**: `id bigint identity PK`, `tenant_id`, `run_id`, `product_id`, `forecast_date date`, `yhat numeric(14,3)`, `yhat_lower numeric(14,3)`, `yhat_upper numeric(14,3)`, `method text`, `event_multiplier numeric(6,3) default 1`, `event_key text null`. `UQ (run_id, product_id, forecast_date)`. Retention: keep the last 8 runs per tenant (prune in the job).

**forecast_backtests**: `id PK`, `tenant_id`, `run_id`, `scope text` (`product|segment|tenant`), `scope_key text` (product uuid, or `category_slug|demand_class`), `method text`, `n_folds smallint`, `n_points int`, `mae numeric(14,4)`, `wape numeric(8,4) null`, `bias numeric(8,4) null`, `rmse numeric(14,4)`, `coverage_ratio numeric(4,3)`, `is_selected boolean default false`, `notes jsonb null`, `created_at`. Index `(tenant_id, run_id, scope)`.

**event_category_effects**: `id PK`, `tenant_id`, `event_key text`, `category_id`, `window text` (`pre|during|post`), `multiplier numeric(6,3)`, `origin text` (`learned|configured`), `n_occurrences smallint`, `n_products smallint`, `consistency numeric(4,3) null`, `evidence jsonb`, `confidence text` (`high|medium|low`), `is_applied boolean`, `computed_at`. `UQ (tenant_id, event_key, category_id, window, origin)`.

**recommendation_runs**: `id PK`, `tenant_id`, `forecast_run_id`, `as_of_date date` (Monday, the order date), `data_cutoff timestamptz`, `budget numeric(14,2) null`, `settings_snapshot jsonb`, `summary jsonb`, `status text` (`running|succeeded|failed`), `started_at`, `finished_at null`, `error text null`, `model_version_id`. `UQ (tenant_id, id)`.

**recommendation_lines**: `id PK`, `tenant_id`, `run_id`, `product_id`, `supplier_id null`, `sections text[]` (subset of `buy|do_not_buy|watch|reduce`), `protection_days smallint`, `lead_time_days smallint`, `lead_time_source text` (`product_term|supplier_default|business_default`), `avg_daily_forecast numeric(14,4)`, `demand_7d numeric(14,3)`, `demand_protection numeric(14,3)`, `on_hand_usable numeric(14,3)`, `expected_expiry_loss numeric(14,3) default 0`, `incoming_confirmed numeric(14,3) default 0`, `incoming_excluded_overdue numeric(14,3) default 0`, `reserved numeric(14,3) default 0`, `inventory_position numeric(14,3)`, `safety_stock numeric(14,3)`, `target_level numeric(14,3)`, `raw_qty numeric(14,3)`, `moq_units numeric(14,3)`, `pack_size numeric(14,3)`, `suggested_qty numeric(14,3)` (after MOQ, pack, expiry cap), `allocated_qty numeric(14,3)` (after budget), `pack_excess_qty numeric(14,3) default 0`, `unit_cost numeric(12,4) null`, `est_spend numeric(14,2) null`, `unfunded_qty numeric(14,3) default 0`, `budget_limited boolean default false`, `stockout_probability numeric(4,3)`, `projected_stockout_date date null`, `days_of_cover numeric(10,2) null`, `risk_level text` (`critical|high|medium|low|none`), `confidence text` (`high|medium|low`), `forecast_method text`, `wape numeric(8,4) null`, `priority_score numeric(6,4) null`, `priority_components jsonb null`, `expiry_exposure_qty numeric(14,3) default 0`, `expiry_exposure_value numeric(14,2) default 0`, `excess_qty numeric(14,3) default 0`, `excess_value numeric(14,2) default 0`, `stock_status text null` (`slow|non_moving|unverified|normal|new`), `event_keys text[]`, `reason_codes text[]`, `reason_text text`, `provenance jsonb` (field -> `observed|calculated|assumed`), `warnings text[]`, `created_at`. `UQ (run_id, product_id)`, `UQ (tenant_id, id)`. Index `(tenant_id, run_id, risk_level)`.

**recommendation_decisions**: `id PK`, `tenant_id`, `line_id`, `decided_by`, `decision text` (`approved|edited|rejected`), `final_qty numeric(14,3)`, `reason_code text null`, `reason_text text null`, `created_at`, `superseded_at timestamptz null`. Partial `UQ (line_id) WHERE superseded_at IS NULL`.

**weekly_reports**: `id PK`, `tenant_id`, `week_start date` (Monday), `version int default 1`, `is_current boolean default true`, `recommendation_run_id`, `forecast_run_id`, `data_cutoff timestamptz`, `status text` (`generating|ready|failed`), `payload jsonb` (see `report-spec.md`), `summary jsonb`, `warnings jsonb`, `model_version text`, `agent_review jsonb null`, `generated_at`, `error text null`. Partial `UQ (tenant_id, week_start) WHERE is_current`. `UQ (tenant_id, week_start, version)`, `UQ (tenant_id, id)`.

**report_notes**: `id PK`, `tenant_id`, `report_id`, `line_id null`, `author_user_id null`, `source text` (`user|agent|chat_pin`), `body text`, `created_at`.

**data_quality_issues**: `id PK`, `tenant_id`, `run_id null`, `code text`, `severity text` (`info|warning|error`), `entity_type text null`, `entity_id uuid null`, `message text`, `detail jsonb null`, `fix_hint text null`, `detected_at`, `resolved_at null`, `resolved_by null`. Partial `UQ NULLS NOT DISTINCT (tenant_id, code, entity_type, entity_id) WHERE resolved_at IS NULL`.

### 2.9 Operations

**job_runs**: `id PK`, `tenant_id null`, `job_name text`, `run_key text` (e.g. `monday_report:2026-10-12`), `status text` (`running|succeeded|failed|skipped`), `attempts int default 1`, `started_at`, `finished_at null`, `result jsonb null`, `error text null`. `UQ NULLS NOT DISTINCT (job_name, run_key, tenant_id)`.

**audit_logs**: `id bigint identity PK`, `tenant_id null`, `user_id null`, `action text` (e.g. `auth.login`, `sale.create`, `decision.approve`), `entity_type text null`, `entity_id text null`, `before jsonb null`, `after jsonb null`, `ip inet null`, `user_agent text null`, `request_id text null`, `created_at`. Index `(tenant_id, created_at desc)`, `(tenant_id, action)`. Immutable: trigger raises on `UPDATE` or `DELETE`.

**idempotency_keys**: `id PK`, `tenant_id`, `key text`, `endpoint text`, `request_hash char(64)`, `response_status smallint`, `response_body jsonb`, `created_at`, `expires_at`. `UQ (tenant_id, key, endpoint)`. Pruned after 48 hours.

### 2.10 Agents and RAG

**chat_threads**: `id PK`, `tenant_id`, `user_id`, `title text`, `page_context jsonb null`, `archived boolean default false`, `created_at`, `last_message_at`. Index `(tenant_id, user_id, last_message_at desc)`.

**chat_messages**: `id PK`, `tenant_id`, `thread_id`, `role text` (`user|assistant`), `content text`, `blocks jsonb null`, `sources jsonb null`, `agent_run_id uuid null`, `feedback smallint default 0` (`-1|0|1`), `feedback_note text null`, `created_at`.

**agent_runs**: `id PK`, `tenant_id`, `user_id null`, `thread_id null`, `kind text` (`chat|monday_review|investigation|scenario_plan|dq_scan|supplier_prep`), `status text` (`running|succeeded|failed|capped|fallback`), `input jsonb`, `output jsonb null`, `model_name text null`, `tokens_in int default 0`, `tokens_out int default 0`, `steps_count int default 0`, `limits jsonb`, `error text null`, `started_at`, `finished_at null`. `UQ (tenant_id, id)`.

**agent_steps**: `id bigint identity PK`, `tenant_id`, `run_id`, `idx int`, `node text`, `step_type text` (`llm|tool|retrieval|verify|safety`), `name text`, `input jsonb null`, `output jsonb null`, `latency_ms int`, `tokens int default 0`, `error text null`, `created_at`. Stored for audit and evals. **Never returned by any user API.**

**agent_actions**: `id PK`, `tenant_id`, `run_id null`, `thread_id null`, `action_type text` (`approve_lines|fix_data_issue|create_report_note|create_draft_pos`), `payload jsonb`, `status text default 'pending'` (`pending|confirmed|rejected|expired|failed`), `proposed_at`, `expires_at`, `resolved_by null`, `resolved_at null`, `result jsonb null`.

**knowledge_documents**: `id PK`, `tenant_id null` (null = global), `doc_type text` (`supplier_policy|decision_memory|report_narrative|app_knowledge|product_note`), `title text`, `source_ref text null`, `metadata jsonb null`, `content_hash char(64)`, `created_at`. `UQ NULLS NOT DISTINCT (tenant_id, doc_type, source_ref, content_hash)`.

**knowledge_chunks**: `id PK`, `document_id`, `tenant_id null`, `chunk_index int`, `content text`, `token_count int`, `embedding vector(768) null`, `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`, `metadata jsonb null`, `created_at`. Indexes: `HNSW (embedding vector_cosine_ops)`, `GIN (tsv)`, `(tenant_id, document_id)`. Retrieval always filters `tenant_id = :tenant OR tenant_id IS NULL`.

**LangGraph checkpoint tables** (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) are created by `PostgresSaver.setup()`, not by Alembic. Exclude them in `alembic/env.py` `include_object`. A migration step enables RLS on them after setup.

---

## 3. Views

```sql
CREATE VIEW v_product_stock AS
SELECT tenant_id, product_id,
       SUM(on_hand) AS on_hand, SUM(reserved_qty) AS reserved,
       SUM(on_hand * avg_unit_cost) AS stock_value
FROM stock_balances GROUP BY tenant_id, product_id;

CREATE VIEW v_batch_stock AS
SELECT b.tenant_id, b.id AS batch_id, b.product_id, b.batch_no, b.expiry_date,
       (b.expiry_date - CURRENT_DATE) AS days_to_expiry,
       COALESCE(s.on_hand,0) AS on_hand, b.unit_cost,
       COALESCE(s.on_hand,0) * b.unit_cost AS value
FROM product_batches b
LEFT JOIN stock_balances s ON s.tenant_id=b.tenant_id AND s.batch_id=b.id;
```

Use `security_invoker = true` on views (PG15+) so RLS is respected.

## 4. Business rules enforced in the database

- No negative balances (`CHECK on_hand >= 0`).
- No cross-tenant references (composite FKs).
- Single primary supplier term per product (partial unique).
- One current report per tenant and week (partial unique).
- One live decision per recommendation line (partial unique).
- Audit log immutable (trigger).
- Exception receipts need a note (`CHECK`).

Rules enforced in services (with tests): receipt quantity within open PO quantity; returned quantity within sold quantity; batch issue within batch balance; cancelled PO not incoming; expired or damaged stock not sellable; sale void only once.

## 5. Movement semantics

| Event | Movements |
|---|---|
| Sale line | `sale`, negative, on the allocated batch |
| Void sale | `void_reversal`, positive, mirrors each sale movement, `reverses_movement_id` set |
| Return, restock | `return_in`, positive |
| Return, damaged or expired | `return_in` positive then `damage` or `expiry_writeoff` negative (net zero usable stock, write-off recorded) |
| Goods receipt | `receipt`, positive, per batch, with `unit_cost` |
| Adjustment | `adjustment` or reason specific type, signed |
| Count correction | `count_correction`, variance |
| Opening balance | `opening`, positive, dated before the first transaction |

Weighted average cost is updated on `receipt` and `opening` only.

## 6. Reconciliation queries (run in tests and in the DQ job)

```sql
-- balances equal ledger
SELECT b.tenant_id, b.product_id, b.batch_id, b.on_hand, COALESCE(m.sum_delta,0) AS ledger
FROM stock_balances b
LEFT JOIN (SELECT tenant_id, product_id, batch_id, SUM(quantity_delta) sum_delta
           FROM inventory_movements GROUP BY 1,2,3) m
  ON m.tenant_id=b.tenant_id AND m.product_id=b.product_id
 AND m.batch_id IS NOT DISTINCT FROM b.batch_id
WHERE b.on_hand <> COALESCE(m.sum_delta,0);

-- sale totals equal lines
SELECT s.id FROM sales s JOIN sale_lines l ON l.sale_id=s.id AND l.tenant_id=s.tenant_id
GROUP BY s.id, s.total, s.discount_total HAVING SUM(l.line_total) <> s.total;

-- PO received equals receipts
SELECT pl.id FROM purchase_order_lines pl
LEFT JOIN receipt_lines rl ON rl.po_line_id=pl.id
LEFT JOIN goods_receipts g ON g.id=rl.receipt_id AND g.status='posted'
GROUP BY pl.id, pl.quantity_received
HAVING pl.quantity_received <> COALESCE(SUM(rl.quantity_received) FILTER (WHERE g.id IS NOT NULL),0);
```

All three must return zero rows after seeding and after every test scenario.

## 7. Migrations plan (Alembic)

Naming `NNNN_slug.py`. Sequence:
1. `0001_extensions_reference` (extensions, `set_updated_at`, tax_rates, calendar_events, model_versions)
2. `0002_tenancy_auth` (tenants, users, refresh_tokens, business_settings)
3. `0003_catalogue_suppliers` (also creates `product_batches`, because sales, returns and receipt lines reference it before `0006` would run, `D-044`)
4. `0004_sales`
5. `0005_purchasing`
6. `0006_inventory` (movements, balances, counts, adjustments, stockouts)
7. `0007_derived_intelligence` (daily stats, synthetic demand, forecast, backtests, effects, recommendations, reports, notes, DQ)
8. `0008_ops_audit` (job_runs, audit, idempotency, immutability trigger)
9. `0009_agents_rag` (chat, agent tables, knowledge, HNSW and GIN)
10. `0010_rls_views_grants` (enable RLS everywhere, revoke grants, views)
11. `0011_auth_lockout_counts` (`users.last_failed_login_at`, `stock_count_lines.counted_qty` nullable, `D-055`)

Migrations must be reversible where practical, and run clean on an empty database and on top of seeded data. Test: `alembic upgrade head`, `downgrade base`, `upgrade head`.

## 8. Size budget (Supabase free: 500 MB)

| Table group | Rows (all four tenants) | Estimate |
|---|---|---|
| `sale_lines` + indexes | about 350k | 80 to 100 MB |
| `inventory_movements` + indexes | about 400k | 70 to 90 MB |
| `sales` | about 110k | 20 MB |
| `daily_product_stats` | about 255k | 25 MB |
| `synthetic_true_demand` | about 255k | 15 MB |
| `forecast_values` (8 runs kept) | about 120k | 10 MB |
| `recommendation_lines` (9 weeks) | about 5k | 5 MB |
| `knowledge_chunks` with vectors | about 3k | 15 MB |
| Everything else | small | under 20 MB |
| **Total** | | **about 260 to 320 MB planned, 359 MB measured after the Prompt 3 seed (see section 12)** |

`seed/size_report.py` prints per table size. If total exceeds 400 MB, lower `--scale` or history length, do not delete indexes blindly. Reclaim space with `VACUUM FULL` only on demo reset.

## 9. Indexing rules (as built)

Every foreign key used in joins has a leading `tenant_id` index. Time series tables index `(tenant_id, product_id, date)`. Use `EXPLAIN` on the five heaviest queries (rollup, stock levels list, product history, report lines, expiry list) and record findings in `memory.md`.

Prompt 1 built only the indexes listed in section 2, plus `(tenant_id, parent_id)` style indexes on `sale_return_lines`, `receipt_lines`, `agent_steps` and `chat_messages`. The `UNIQUE (tenant_id, ...)` constraints already give a leading `tenant_id` index for parent lookups. The remaining child foreign key indexes are decided by the `EXPLAIN` pass in P8.02, not guessed now.

---

## 10. As built in Prompt 1 (schema decisions beyond the tables above)

These were needed to make the schema creatable and are logged in `memory.md`.

| Topic | What was built |
|---|---|
| Extra `UNIQUE (tenant_id, id)` | `refresh_tokens`, `inventory_movements`, `promotions` and `chat_threads`, on top of the parents the tables above already list, so `replaced_by_id`, `reverses_movement_id`, `stock_adjustments.movement_id` and `sale_return_lines.sale_line_id` are composite as well (`D-046`) |
| Plain foreign keys by design | To `tenants`, `users`, `model_versions`, `tax_rates`, `knowledge_documents` only. `created_by`, `voided_by`, `decided_by`, `resolved_by`, `author_user_id` are plain keys to `users(id)` as the convention says |
| Soft references (plain uuid, no foreign key) | `purchase_orders.recommendation_run_id`, `purchase_order_lines.recommendation_line_id` (plans are created in a later migration), `data_quality_issues.run_id` (the DQ step runs before any plan row exists), `chat_messages.agent_run_id` |
| `audit_logs` | `tenant_id` and `user_id` are plain columns, not keys, so the immutable log never blocks deleting a tenant on demo reset. A trigger rejects `UPDATE`, `DELETE` and `TRUNCATE` |
| Knowledge tables | `tenant_id` is nullable (global documents), so keys stay plain. `knowledge_chunks.document_id` is `ON DELETE CASCADE` so re-ingestion can replace a document |
| Defaults added | `server_default '{}'` on jsonb config columns that are objects (`config`, `settings_snapshot`, `summary`, `evidence`, `provenance`, `agent_runs.input`, `limits`), `'[]'` for `weekly_reports.warnings`, `'{}'` for text array columns, `users.password_changed_at` defaults to `now()` |
| `window` column | `event_category_effects.window` is a reserved word in PostgreSQL. SQLAlchemy quotes it, and the CHECK helper quotes every column name |
| Tables without `created_at` | Follow the table definitions literally: `categories`, `business_settings` (has `updated_at`), `refresh_tokens` (has `issued_at`) and the append-only line tables have none |
| Views | `days_to_expiry` counts from the IST business date, `(now() AT TIME ZONE 'Asia/Kolkata')::date`, not `CURRENT_DATE` (`D-048`). Both views use `security_invoker = true` |
| RLS step | Enabled on every table in `public` at migration time, including `alembic_version`. LangGraph checkpoint tables are created later by `PostgresSaver.setup()`, so P7 must run the same RLS statement after setup |
| Supabase roles | The revoke step checks that `anon` and `authenticated` exist, so it is a no-op on plain local Postgres. `PUBLIC` keeps `USAGE` on schema `public` by default, which is why the migration revokes table, sequence and function grants and the test checks the explicit ACL |
| Extensions | `vector`, `citext`, `pg_trgm`, `pgcrypto`. `gen_random_uuid()` is built in from PostgreSQL 13, `pgcrypto` stays for any later digest use |

---

## 11. As built in Prompt 2

| Topic | What was built |
|---|---|
| Migration `0011` | `users.last_failed_login_at`, `stock_count_lines.counted_qty` and the generated `variance` nullable (`D-055`) |
| Document numbers | Bills `B{YYMM}-{seq:05d}`, returns `R{YYMM}-{seq:04d}`, orders `PO{YYMM}-{seq:04d}`, receipts `GR{YYMM}-{seq:04d}`. A per tenant advisory lock serialises the next number |
| Movement `source_type` and `source_id` | Sale: `sale`, the sale id. Void: `void`, the sale id. Return: `sale_return`, the return id. Receipt: `receipt`, the receipt id. Adjustment, write off and supplier return: `adjustment`, the `stock_adjustments` id. Count: `stock_count`, the count id |
| Bill money | Prices include GST. `subtotal` is the sum of line amounts before discount, `total = subtotal - discount_total` and equals the sum of `line_total`. `tax_total` is the tax contained in the lines |
| Expiry | A batch is sellable while `expiry_date > business date` (the expiry date is the first day it cannot be sold) |
| Idempotency | `idempotency_keys` unique on tenant, key and scope (`POST /sales`, `POST /sales/<id>/returns` and so on). `sales.idempotency_key` stays null when an expired key is reused |
| Reconciliation | `services/reconciliation.py` runs the three queries of section 6 plus a returned quantity check, scoped to a tenant |


---

## 12. As built in Prompt 3

| Topic | What was built |
|---|---|
| Migration `0012` | Partial index `ix_inventory_movements_tenant_reverses` on `(tenant_id, reverses_movement_id) WHERE reverses_movement_id IS NOT NULL`. Needed because the column is a foreign key to the same table, and a delete scanned the whole table once per row (`D-066`) |
| Seeded rows | `sales.source = 'seed'`. Ids are deterministic uuids `5eed{tenant}-{kind}-4000-8000-{n}`, identity ids for sale lines, movements and return lines are offset by the tenant index times 10 million. Document numbers follow the service formats (`B{YYMM}-{seq:05d}`, `R`, `PO`, `GR`) and restart each month |
| Movements | Same types and sign rules as `engine/ledger_rules.py`. Sale movements carry the batch cost (or the running average cost). A void posts `void_reversal` at the bill's own time. Counts post `count_correction`, adjustments post one movement plus one `stock_adjustments` row whose id is the movement's `source_id` |
| Balances | Rebuilt from the ledger with one `INSERT ... SELECT` after the load, average cost taken from the simulation and checked by the reconciliation queries. Batch tracked products have one row per batch, others one row with a null batch |
| Null batch stock | The S10 product that is batch tracked but has no batch keeps its stock under a null batch, which is how `MISSING_EXPIRY` shows up |
| `daily_product_stats` | Written by `services/rollup.py` (the rollup service, which replaced the Prompt 3 SQL fallback, `D-082`) for the whole history (546 days per product). Replaced by the rollup service in P4.24 |
| Reset | `seed.run --reset` deletes the chosen tenants from every tenant owned base table, children first (order read from the foreign keys), keeps `audit_logs`, then runs `VACUUM FULL` on the large tables |
| Sizes after the full seed | `inventory_movements` 110 MB, `sale_lines` 85 MB, `daily_product_stats` 59 MB, `sales` 44 MB, `synthetic_true_demand` 38 MB, everything else about 25 MB. Total 359.0 MB (370 MB on disk) |
