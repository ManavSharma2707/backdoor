import type { ReactNode } from "react";
import { Link } from "react-router";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { Button } from "./button";
import { Tip } from "./overlay";

// ------------------------------------------------------------------ status and risk

const chip = cva(
  "inline-flex h-5 items-center rounded-sm px-1.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-surface-3 text-text-2",
        ok: "bg-ok-soft text-ok",
        info: "bg-info-soft text-info",
        medium: "bg-medium-soft text-medium",
        high: "bg-high-soft text-high",
        critical: "bg-critical-soft text-critical",
        accent: "bg-accent-soft text-accent",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type Tone = "neutral" | "ok" | "info" | "medium" | "high" | "critical" | "accent";

/** A filled chip, only for statuses that need scanning (order status, stock status, decision). */
export function StatusChip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={chip({ tone })}>{children}</span>;
}

const dotTone: Record<string, string> = {
  critical: "bg-critical text-critical",
  high: "bg-high text-high",
  medium: "bg-medium text-medium",
  low: "bg-ok text-ok",
  ok: "bg-ok text-ok",
  none: "bg-text-3 text-text-2",
};

/** Risk is a small dot plus the word, never colour alone. */
export function RiskText({ level, label }: { level: string; label: string }) {
  const tone = dotTone[level] ?? dotTone["none"];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", tone?.split(" ")[1])}>
      <span className={cn("size-2 rounded-full", tone?.split(" ")[0])} aria-hidden="true" />
      {label}
    </span>
  );
}

const provenanceTone = {
  observed: "text-observed",
  calculated: "text-calculated",
  assumed: "text-assumed",
} as const;

export function ProvenanceTag({
  kind,
  label,
  explanation,
}: {
  kind: keyof typeof provenanceTone;
  label: string;
  explanation: string;
}) {
  return (
    <Tip label={explanation}>
      <button
        type="button"
        className={cn(
          "cursor-help border-b border-dotted border-current text-xs tracking-[0.02em] uppercase",
          provenanceTone[kind],
        )}
      >
        {label}
      </button>
    </Tip>
  );
}

// ------------------------------------------------------------------ banner

const banner = cva("flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md px-4 py-2.5 text-base", {
  variants: {
    tone: {
      info: "bg-info-soft text-text",
      warning: "bg-medium-soft text-text",
      error: "bg-critical-soft text-text",
      ok: "bg-ok-soft text-text",
    },
  },
  defaultVariants: { tone: "info" },
});

export function Banner({
  tone = "info",
  children,
  action,
  className,
}: {
  tone?: "info" | "warning" | "error" | "ok";
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn(banner({ tone }), className)}>
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

/** A banner that asks the person to retry a failed load. */
export function ErrorBanner({
  message,
  onRetry,
  retryLabel,
}: {
  message: string;
  onRetry?: () => void;
  retryLabel: string;
}) {
  return (
    <Banner
      tone="error"
      action={
        onRetry ? (
          <Button size="sm" onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : undefined
      }
    >
      {message}
    </Banner>
  );
}

// ------------------------------------------------------------------ empty state and skeleton

/** What is missing, what to do, one button. Left aligned. */
export function EmptyState({
  title,
  hint,
  action,
  className,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-start gap-3 px-4 py-8", className)}>
      <p className="text-base">
        {title}
        {hint ? <span className="text-text-2"> {hint}</span> : null}
      </p>
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} aria-hidden="true" />;
}

// ------------------------------------------------------------------ panel and layout

export function Panel({
  title,
  action,
  children,
  className,
  flush,
  id,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  /** No padding, for tables that touch the panel edge. */
  flush?: boolean;
  id?: string;
}) {
  return (
    <section id={id} className={cn("rounded-md border border-border bg-surface", className)}>
      {title || action ? (
        <header className="flex items-center justify-between gap-3 px-4 pt-4">
          {title ? <h2 className="text-md font-medium">{title}</h2> : <span />}
          {action}
        </header>
      ) : null}
      <div className={cn(flush ? "" : "p-4 pt-3")}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  context,
  actions,
}: {
  title: string;
  context?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">{title}</h1>
        {context ? <p className="mt-0.5 text-base text-text-2">{context}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export type Kpi = {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  to?: string;
};

/** Several key numbers in one panel, separated by rules. */
export function KpiStrip({ items, className }: { items: Kpi[]; className?: string }) {
  return (
    <section
      className={cn(
        "grid divide-y divide-border rounded-md border border-border bg-surface sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-5 lg:divide-x",
        className,
      )}
    >
      {items.map((item) => {
        const inner = (
          <>
            <div className="text-sm text-text-2">{item.label}</div>
            <div className="tabular mt-1 text-kpi font-semibold">{item.value}</div>
            {item.hint ? <div className="mt-1 text-xs text-text-3">{item.hint}</div> : null}
          </>
        );
        return item.to ? (
          <Link
            key={item.label}
            to={item.to}
            className="block px-4 py-3 hover:bg-surface-2 sm:border-b sm:border-border lg:border-b-0"
          >
            {inner}
          </Link>
        ) : (
          <div key={item.label} className="px-4 py-3 sm:border-b sm:border-border lg:border-b-0">
            {inner}
          </div>
        );
      })}
    </section>
  );
}

/** A label above a value, used in detail headers and summaries. */
export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-text-2">{label}</div>
      <div className="tabular text-md font-medium">{value}</div>
      {hint ? <div className="text-xs text-text-3">{hint}</div> : null}
    </div>
  );
}

/** Key and value rows for details. */
export function KeyValueList({ rows }: { rows: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-x-4 gap-y-2 text-base">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-text-2">{row.label}</dt>
          <dd className="tabular min-w-0 break-words">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-sm", className)}>{children}</span>;
}
