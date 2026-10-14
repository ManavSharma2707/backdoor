import { lazy, Suspense } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";
import { useApiQuery, useSettings } from "@/lib/queries";
import {
  addDays,
  compactMoney,
  dateRange,
  formatDate,
  formatDateTime,
  formatDayMonth,
  money,
  quantity,
} from "@/lib/format";
import { common } from "@/copy/common";
import { overview as copy } from "@/copy/overview";
import type {
  ActivityItem,
  BatchRow,
  CoverResponse,
  DashboardSummary,
  Page,
  PurchaseListItem,
  TrendsResponse,
} from "@/types/models";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorBanner,
  KpiStrip,
  PageHeader,
  Panel,
  RiskText,
  Skeleton,
} from "@/components/ui/display";

const SalesTrendChart = lazy(() => import("./charts"));

const EXPIRY_DAYS = 14;
const COVER_CAP_DAYS = 60;
const MAX_ROWS = 8;

type Row = {
  key: string;
  level: "critical" | "high" | "medium";
  text: string;
  to: string;
  action: string;
};

function useAttentionData(summary: DashboardSummary | undefined) {
  const expiring = useApiQuery<Page<BatchRow>>("/inventory/batches", {
    expiring_within_days: EXPIRY_DAYS,
    page_size: 1,
  });
  const overdue = useApiQuery<Page<PurchaseListItem>>("/purchase-orders", {
    overdue: true,
    page_size: 1,
  });
  const planId = summary?.plan?.id;
  const waiting = useQuery({
    queryKey: ["plan-waiting", planId],
    enabled: Boolean(planId),
    queryFn: async () => {
      const [pending, all] = await Promise.all([
        get<Page<unknown>>(`/reports/${planId}/lines`, {
          section: "buy",
          decision: "pending",
          page_size: 1,
        }),
        get<Page<unknown>>(`/reports/${planId}/lines`, { section: "buy", page_size: 1 }),
      ]);
      return { pending: pending.total, total: all.total };
    },
  });
  return { expiring, overdue, waiting };
}

function buildRows(
  summary: DashboardSummary,
  expiring: number,
  overdue: number,
  waiting: { pending: number; total: number } | undefined,
): { rows: Row[]; hiddenLines: number } {
  const extra: Row[] = [];
  if (expiring > 0) {
    extra.push({
      key: "expiry",
      level: "high",
      text: copy.attention.expiring(expiring, EXPIRY_DAYS),
      to: "/stock?tab=batches&window=30",
      action: copy.attention.openBatches,
    });
  }
  if (overdue > 0) {
    extra.push({
      key: "overdue",
      level: "high",
      text: copy.attention.overdue(overdue),
      to: "/purchases?overdue=true",
      action: copy.attention.openOrders,
    });
  }
  if (summary.kpis.data_errors > 0) {
    extra.push({
      key: "data",
      level: "medium",
      text: copy.attention.dataErrors(summary.kpis.data_errors),
      to: "/plan?tab=data-notes",
      action: copy.attention.openDataNotes,
    });
  }
  if (waiting && waiting.pending > 0) {
    extra.push({
      key: "decisions",
      level: "medium",
      text: copy.attention.decisions(waiting.pending, waiting.total),
      to: "/plan",
      action: copy.attention.openPlan,
    });
  }
  const room = Math.max(0, MAX_ROWS - extra.length);
  const lines = summary.needs_attention.filter((item) => item.name);
  const shown: Row[] = lines.slice(0, room).map((item) => ({
    key: `line-${item.line_id ?? item.sku}`,
    level: item.risk_level === "high" ? "high" : "critical",
    text: copy.attention.line(item.name ?? "", item.headline ?? ""),
    to: `/products?q=${encodeURIComponent(item.sku ?? "")}`,
    action: copy.attention.openLine,
  }));
  return { rows: [...shown, ...extra], hiddenLines: Math.max(0, lines.length - shown.length) };
}

function NeedsAttention({ summary }: { summary: DashboardSummary }) {
  const { expiring, overdue, waiting } = useAttentionData(summary);
  const { rows, hiddenLines } = buildRows(
    summary,
    expiring.data?.total ?? 0,
    overdue.data?.total ?? 0,
    waiting.data,
  );
  return (
    <Panel title={copy.attention.title}>
      {rows.length === 0 ? (
        <p className="py-2 text-base text-text-2">{copy.attention.empty}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li key={row.key} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
              <span className="w-20 shrink-0">
                <RiskText level={row.level} label={copy.attention.risk[row.level]} />
              </span>
              <span className="min-w-0 flex-1 text-base">{row.text}</span>
              <Link to={row.to} className="text-sm font-medium text-link hover:underline">
                {row.action}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {hiddenLines > 0 ? (
        <p className="mt-2 text-sm text-text-3">{copy.attention.moreLines(hiddenLines)}</p>
      ) : null}
    </Panel>
  );
}

function Kpis({ summary }: { summary: DashboardSummary }) {
  const cover = useApiQuery<CoverResponse>("/dashboard/cover-by-category");
  const expiring = useApiQuery<Page<BatchRow>>("/inventory/batches", {
    expiring_within_days: 90,
    page_size: 1,
  });
  const k = summary.kpis;
  const atRisk = cover.data
    ? cover.data.categories.reduce((sum, c) => sum + c.critical_lines + c.high_lines, 0)
    : k.critical_lines;
  const batches = expiring.data?.total;
  return (
    <KpiStrip
      items={[
        {
          label: copy.kpi.stockValue,
          value: compactMoney(k.stock_value),
          hint: copy.kpi.stockValueHint,
          to: "/stock",
        },
        {
          label: copy.kpi.spend,
          value: compactMoney(k.suggested_spend),
          hint: k.budget ? copy.kpi.spendBudget(money(k.budget)) : copy.kpi.spendNoBudget,
          to: "/plan",
        },
        { label: copy.kpi.atRisk, value: quantity(atRisk), hint: copy.kpi.atRiskHint, to: "/plan" },
        {
          label: copy.kpi.notMoving,
          value: compactMoney(k.non_moving_value),
          hint: copy.kpi.notMovingHint,
          to: "/stock?status=ok",
        },
        {
          label: copy.kpi.nearExpiry,
          value: compactMoney(k.near_expiry_value),
          hint: batches ? copy.kpi.nearExpiryHint(batches) : copy.kpi.nearExpiryNoBatches,
          to: "/stock?tab=batches&window=90",
        },
      ]}
    />
  );
}

function TrendPanel() {
  const trends = useApiQuery<TrendsResponse>("/dashboard/trends", { weeks: 12 });
  const best = trends.data?.weeks.reduce<TrendsResponse["weeks"][number] | null>(
    (top, week) => (!top || Number(week.revenue) > Number(top.revenue) ? week : top),
    null,
  );
  const hasSales = Boolean(best && Number(best.revenue) > 0);
  return (
    <Panel title={copy.trend.title}>
      {trends.isError ? (
        <ErrorBanner
          message={copy.loadFailed}
          onRetry={() => void trends.refetch()}
          retryLabel={common.retry}
        />
      ) : trends.isLoading ? (
        <Skeleton className="h-[220px] w-full" />
      ) : !trends.data || !hasSales ? (
        <EmptyState title={copy.trend.empty} />
      ) : (
        <>
          <p className="mb-2 text-sm text-text-2">
            {copy.trend.summary(formatDayMonth(best?.week_start), money(best?.revenue))}
          </p>
          <Suspense fallback={<Skeleton className="h-[220px] w-full" />}>
            <SalesTrendChart data={trends.data} />
          </Suspense>
          {trends.data.festival_bands.length > 0 ? (
            <p className="mt-2 text-xs text-text-3">
              {copy.trend.shaded(
                trends.data.festival_bands.map(
                  (band) => `${band.name} (${dateRange(band.start, band.end)})`,
                ),
              )}
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

function CoverPanel() {
  const cover = useApiQuery<CoverResponse>("/dashboard/cover-by-category");
  const settings = useSettings();
  const review = settings.data?.review_period_days ?? 7;
  const rows = (cover.data?.categories ?? [])
    .filter((c) => c.days_of_cover !== null)
    .sort((a, b) => (a.days_of_cover ?? 0) - (b.days_of_cover ?? 0));
  const thinnest = rows[0];
  return (
    <Panel title={copy.cover.title}>
      {cover.isError ? (
        <ErrorBanner
          message={copy.loadFailed}
          onRetry={() => void cover.refetch()}
          retryLabel={common.retry}
        />
      ) : cover.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={copy.cover.empty} />
      ) : (
        <>
          <p className="mb-3 text-sm text-text-2">
            {copy.cover.summary(
              thinnest?.category ?? "",
              (thinnest?.days_of_cover ?? 0).toFixed(1),
            )}
          </p>
          <ul className="relative space-y-2">
            {rows.map((row) => {
              const days = row.days_of_cover ?? 0;
              return (
                <li
                  key={row.category_id}
                  className="grid grid-cols-[minmax(0,10rem)_1fr_5.5rem] items-center gap-3 text-sm"
                >
                  <span className="truncate" title={row.category}>
                    {row.category}
                  </span>
                  <span className="relative h-3 rounded-sm bg-surface-2">
                    <span
                      className="absolute inset-y-0 left-0 rounded-sm bg-chart-1"
                      style={{
                        width: `${Math.max(1, (Math.min(days, COVER_CAP_DAYS) / COVER_CAP_DAYS) * 100)}%`,
                      }}
                    />
                    <span
                      className="absolute -inset-y-1 w-px bg-accent"
                      style={{ left: `${(review / COVER_CAP_DAYS) * 100}%` }}
                      aria-hidden="true"
                    />
                  </span>
                  <span className="tabular text-right">{copy.cover.days(days.toFixed(1))}</span>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 text-xs text-text-3">
            <span
              className="mr-1.5 inline-block h-3 w-px translate-y-0.5 bg-accent"
              aria-hidden="true"
            />
            {copy.cover.reviewRule(review)}. {copy.cover.capped(COVER_CAP_DAYS)}
          </p>
        </>
      )}
    </Panel>
  );
}

function PlanPanel({ summary }: { summary: DashboardSummary }) {
  const { waiting } = useAttentionData(summary);
  const plan = summary.plan;
  const critical = summary.needs_attention
    .filter((item) => item.risk_level === "critical")
    .slice(0, 3);
  return (
    <Panel title={copy.plan.title}>
      {!plan ? (
        <EmptyState title={copy.plan.none} hint={copy.plan.noneHint} />
      ) : (
        <div className="space-y-3">
          <div>
            <div className="text-base font-medium">
              {waiting.data && waiting.data.pending > 0
                ? copy.plan.waiting(waiting.data.pending, waiting.data.total)
                : waiting.data
                  ? copy.plan.allDecided(waiting.data.total)
                  : copy.plan.week(formatDayMonth(plan.week_start))}
            </div>
            <div className="text-sm text-text-3">
              {copy.plan.week(formatDayMonth(plan.week_start))}
            </div>
          </div>
          {critical.length > 0 ? (
            <div>
              <div className="mb-1 text-xs text-text-2">{copy.plan.topLines}</div>
              <ul className="space-y-1 text-base">
                {critical.map((item) => (
                  <li key={item.line_id} className="truncate">
                    {item.name}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <Link to="/plan">
            <Button variant="primary">{copy.plan.open}</Button>
          </Link>
        </div>
      )}
    </Panel>
  );
}

function activityText(item: ActivityItem): string {
  switch (item.kind) {
    case "bill_saved":
      return copy.activity.billSaved(item.ref);
    case "bill_voided":
      return copy.activity.billVoided(item.ref);
    case "goods_received":
      return copy.activity.goodsReceived(item.party ?? "");
    case "order_created":
      return copy.activity.orderCreated(item.ref, item.party ?? "");
  }
}

function activityLink(item: ActivityItem): string | null {
  if (item.kind === "bill_saved" || item.kind === "bill_voided") return `/sales/${item.entity_id}`;
  if (item.kind === "order_created") return `/purchases/${item.entity_id}`;
  return null;
}

function ActivityPanel() {
  const activity = useApiQuery<{ items: ActivityItem[] }>("/dashboard/activity", { limit: 8 });
  return (
    <Panel title={copy.activity.title}>
      {activity.isError ? (
        <ErrorBanner
          message={copy.loadFailed}
          onRetry={() => void activity.refetch()}
          retryLabel={common.retry}
        />
      ) : activity.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : activity.data?.items.length ? (
        <ul className="divide-y divide-border">
          {activity.data.items.map((item) => {
            const link = activityLink(item);
            const text = activityText(item);
            return (
              <li
                key={`${item.kind}-${item.entity_id}`}
                className="flex items-baseline justify-between gap-4 py-1.5"
              >
                <span className="min-w-0 truncate text-base">
                  {link ? (
                    <Link to={link} className="hover:underline">
                      {text}
                    </Link>
                  ) : (
                    text
                  )}
                </span>
                <span className="shrink-0 text-xs text-text-3">{formatDateTime(item.at)}</span>
              </li>
            );
          })}
        </ul>
      ) : (
        <EmptyState title={copy.activity.empty} />
      )}
    </Panel>
  );
}

export default function OverviewPage() {
  const summary = useApiQuery<DashboardSummary>("/dashboard/summary");
  const plan = summary.data?.plan;
  const dataUpTo = plan ? formatDate(addDays(plan.week_start, -1)) : null;

  return (
    <>
      <PageHeader title={copy.title} context={dataUpTo ? common.dataUpTo(dataUpTo) : undefined} />
      {summary.isError ? (
        <ErrorBanner
          message={copy.loadFailed}
          onRetry={() => void summary.refetch()}
          retryLabel={common.retry}
        />
      ) : summary.isLoading || !summary.data ? (
        <div className="space-y-6" aria-busy="true">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-24 w-full" />
          <div className="grid gap-6 lg:grid-cols-2">
            <Skeleton className="h-64 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          <NeedsAttention summary={summary.data} />
          <Kpis summary={summary.data} />
          <div className="grid items-start gap-6 lg:grid-cols-2">
            <TrendPanel />
            <CoverPanel />
          </div>
          <div className="grid items-start gap-6 lg:grid-cols-2">
            <PlanPanel summary={summary.data} />
            <ActivityPanel />
          </div>
        </div>
      )}
    </>
  );
}
