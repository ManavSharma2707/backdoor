import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { patch, post } from "@/lib/api";
import { useAuth, useSession } from "@/lib/auth";
import { applyServerErrors, errorText, isDecimal } from "@/lib/forms";
import { useQueryParams } from "@/lib/hooks";
import { useApiQuery, useSettings } from "@/lib/queries";
import { addDays, dateRange, formatDate, money, todayIso } from "@/lib/format";
import { common } from "@/copy/common";
import { settings as copy } from "@/copy/settings";
import type { CalendarEvent, Page, Settings, SettingsPatch } from "@/types/models";
import { Button } from "@/components/ui/button";
import { Checkbox, Switch, TabPanel, Tabs } from "@/components/ui/controls";
import {
  Banner,
  EmptyState,
  KeyValueList,
  PageHeader,
  Panel,
  Skeleton,
  StatusChip,
} from "@/components/ui/display";
import { Field, NumberField, SelectField, TextField } from "@/components/ui/field";
import { ConfirmDialog } from "@/components/ui/overlay";
import { notify } from "@/components/ui/pickers";
import { DataTable, type Column } from "@/components/ui/table";

// ------------------------------------------------------------------ business

function BusinessTab() {
  const { tenant } = useSession();
  return (
    <Panel className="max-w-2xl">
      <KeyValueList
        rows={[
          { label: copy.business.name, value: tenant.name },
          {
            label: copy.business.type,
            value:
              copy.business.types[tenant.business_type as keyof typeof copy.business.types] ??
              tenant.business_type,
          },
          { label: copy.business.timezone, value: copy.business.timezoneValue },
          { label: copy.business.currency, value: copy.business.currencyValue },
        ]}
      />
      <p className="mt-4 text-sm text-text-3">{copy.business.readOnly}</p>
      {tenant.is_synthetic ? (
        <p className="mt-2 text-sm text-text-2">{copy.business.demoNote}</p>
      ) : null}
    </Panel>
  );
}

// ------------------------------------------------------------------ planning

const intField = (min: number, max: number) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, copy.planning.errors.number)
    .refine((v) => Number(v) >= min && Number(v) <= max, copy.planning.errors.range(min, max));

const schema = z
  .object({
    noLimit: z.boolean(),
    weekly_budget: z.string().trim(),
    service_level: z.enum(["0.90", "0.95", "0.97", "0.99"]),
    review_period_days: intField(1, 28),
    default_lead_time_days: intField(0, 60),
    near_expiry_days: intField(7, 365),
    nonmoving_days: intField(14, 365),
    slow_cover_days: intField(14, 730),
    excess_horizon_days: intField(7, 180),
    stale_count_days: intField(7, 180),
    shelf_pct: intField(10, 100).refine(() => true),
    pack_rounding: z.enum(["up", "nearest_safe"]),
    w_risk: z.number().min(0).max(100),
    w_value: z.number().min(0).max(100),
    w_confidence: z.number().min(0).max(100),
    w_excess: z.number().min(0).max(100),
    agents_enabled: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (!v.noLimit && !isDecimal(v.weekly_budget, 2)) {
      ctx.addIssue({
        code: "custom",
        path: ["weekly_budget"],
        message: copy.planning.errors.budget,
      });
    }
    if (v.w_risk + v.w_value + v.w_confidence + v.w_excess !== 100) {
      ctx.addIssue({ code: "custom", path: ["w_risk"], message: copy.planning.weightsError });
    }
  });

type Values = z.infer<typeof schema>;

const SERVICE_LEVELS = ["0.90", "0.95", "0.97", "0.99"] as const;

function toValues(s: Settings): Values {
  const level = Number(s.service_level).toFixed(2);
  return {
    noLimit: s.weekly_budget === null,
    weekly_budget: s.weekly_budget === null ? "" : String(Number(s.weekly_budget)),
    service_level: (SERVICE_LEVELS as readonly string[]).includes(level)
      ? (level as Values["service_level"])
      : "0.95",
    review_period_days: String(s.review_period_days),
    default_lead_time_days: String(s.default_lead_time_days),
    near_expiry_days: String(s.near_expiry_days),
    nonmoving_days: String(s.nonmoving_days),
    slow_cover_days: String(s.slow_cover_days),
    excess_horizon_days: String(s.excess_horizon_days),
    stale_count_days: String(s.stale_count_days),
    shelf_pct: String(Math.round(Number(s.sellable_shelf_life_fraction) * 100)),
    pack_rounding: s.pack_rounding,
    w_risk: Math.round(s.priority_weights.risk * 100),
    w_value: Math.round(s.priority_weights.value * 100),
    w_confidence: Math.round(s.priority_weights.confidence * 100),
    w_excess: Math.round(s.priority_weights.excess * 100),
    agents_enabled: s.agents_enabled,
  };
}

function toPatch(v: Values): SettingsPatch {
  return {
    weekly_budget: v.noLimit ? null : v.weekly_budget,
    service_level: v.service_level,
    review_period_days: Number(v.review_period_days),
    default_lead_time_days: Number(v.default_lead_time_days),
    near_expiry_days: Number(v.near_expiry_days),
    nonmoving_days: Number(v.nonmoving_days),
    slow_cover_days: Number(v.slow_cover_days),
    excess_horizon_days: Number(v.excess_horizon_days),
    stale_count_days: Number(v.stale_count_days),
    sellable_shelf_life_fraction: (Number(v.shelf_pct) / 100).toFixed(2),
    pack_rounding: v.pack_rounding,
    priority_weights: {
      risk: v.w_risk / 100,
      value: v.w_value / 100,
      confidence: v.w_confidence / 100,
      excess: v.w_excess / 100,
    },
    agents_enabled: v.agents_enabled,
  };
}

function describeChanges(before: Values, after: Values): string[] {
  const days = (v: string) => `${v} ${copy.planning.days}`;
  const level = (v: string) => `${Math.round(Number(v) * 100)}%`;
  const rows: [string, string, string, boolean][] = [
    [
      copy.planning.budget,
      before.noLimit ? copy.planning.unlimited : money(before.weekly_budget),
      after.noLimit ? copy.planning.unlimited : money(after.weekly_budget),
      before.noLimit !== after.noLimit ||
        (!after.noLimit && Number(before.weekly_budget) !== Number(after.weekly_budget)),
    ],
    [
      copy.planning.serviceLevel,
      level(before.service_level),
      level(after.service_level),
      before.service_level !== after.service_level,
    ],
    [
      copy.planning.review,
      days(before.review_period_days),
      days(after.review_period_days),
      before.review_period_days !== after.review_period_days,
    ],
    [
      copy.planning.leadTime,
      days(before.default_lead_time_days),
      days(after.default_lead_time_days),
      before.default_lead_time_days !== after.default_lead_time_days,
    ],
    [
      copy.planning.nearExpiry,
      days(before.near_expiry_days),
      days(after.near_expiry_days),
      before.near_expiry_days !== after.near_expiry_days,
    ],
    [
      copy.planning.nonMoving,
      days(before.nonmoving_days),
      days(after.nonmoving_days),
      before.nonmoving_days !== after.nonmoving_days,
    ],
    [
      copy.planning.slowCover,
      days(before.slow_cover_days),
      days(after.slow_cover_days),
      before.slow_cover_days !== after.slow_cover_days,
    ],
    [
      copy.planning.excess,
      days(before.excess_horizon_days),
      days(after.excess_horizon_days),
      before.excess_horizon_days !== after.excess_horizon_days,
    ],
    [
      copy.planning.staleCount,
      days(before.stale_count_days),
      days(after.stale_count_days),
      before.stale_count_days !== after.stale_count_days,
    ],
    [
      copy.planning.shelfLife,
      `${before.shelf_pct}%`,
      `${after.shelf_pct}%`,
      before.shelf_pct !== after.shelf_pct,
    ],
    [
      copy.planning.packRounding,
      before.pack_rounding === "up" ? copy.planning.roundUp : copy.planning.roundNearest,
      after.pack_rounding === "up" ? copy.planning.roundUp : copy.planning.roundNearest,
      before.pack_rounding !== after.pack_rounding,
    ],
    [
      copy.planning.weightRisk,
      `${before.w_risk}`,
      `${after.w_risk}`,
      before.w_risk !== after.w_risk,
    ],
    [
      copy.planning.weightValue,
      `${before.w_value}`,
      `${after.w_value}`,
      before.w_value !== after.w_value,
    ],
    [
      copy.planning.weightConfidence,
      `${before.w_confidence}`,
      `${after.w_confidence}`,
      before.w_confidence !== after.w_confidence,
    ],
    [
      copy.planning.weightExcess,
      `${before.w_excess}`,
      `${after.w_excess}`,
      before.w_excess !== after.w_excess,
    ],
    [
      copy.planning.assistant,
      before.agents_enabled ? copy.planning.on : copy.planning.off,
      after.agents_enabled ? copy.planning.on : copy.planning.off,
      before.agents_enabled !== after.agents_enabled,
    ],
  ];
  return rows.filter((r) => r[3]).map(([label, from, to]) => copy.planning.change(label, from, to));
}

function WeightSlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={`${label}: ${value}`}>
      {(ids) => (
        <input
          {...ids}
          type="range"
          min={0}
          max={100}
          step={5}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-primary"
        />
      )}
    </Field>
  );
}

function PlanningTab() {
  const queryClient = useQueryClient();
  const current = useSettings();
  const [confirming, setConfirming] = useState<string[] | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError,
    getValues,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), mode: "onBlur" });

  const baseline = useMemo(() => (current.data ? toValues(current.data) : null), [current.data]);
  useEffect(() => {
    if (baseline) reset(baseline);
  }, [baseline, reset]);

  const noLimit = useWatch({ control, name: "noLimit" });
  const weights = useWatch({ control, name: ["w_risk", "w_value", "w_confidence", "w_excess"] });
  const total = (weights ?? []).reduce((sum, w) => sum + (w ?? 0), 0);

  const save = useMutation({
    mutationFn: (values: Values) => patch<Settings>("/settings", toPatch(values)),
    onSuccess: () => {
      notify.success(copy.planning.saved);
      setConfirming(null);
      void queryClient.invalidateQueries({ queryKey: ["/settings", {}] });
      void queryClient.invalidateQueries({ queryKey: ["/auth/me"] });
    },
    onError: (error) => {
      setConfirming(null);
      setFormError(applyServerErrors(error, setError, ["weekly_budget", "service_level"]));
    },
  });

  if (current.isLoading || !baseline) return <Skeleton className="h-96 w-full" />;
  if (current.isError) return <Banner tone="error">{copy.loadFailed}</Banner>;

  const onSubmit = handleSubmit((values) => {
    setFormError(null);
    const changes = describeChanges(baseline, values);
    if (changes.length === 0) {
      setInfo(copy.planning.nothingChanged);
      return;
    }
    setInfo(null);
    setConfirming(changes);
  });

  return (
    <form onSubmit={onSubmit} noValidate className="max-w-3xl space-y-6">
      <p className="text-base text-text-2">{copy.planning.intro}</p>
      {formError ? <Banner tone="error">{formError}</Banner> : null}
      <Panel>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <NumberField
              label={copy.planning.budget}
              suffix="₹"
              hint={copy.planning.budgetHint}
              disabled={noLimit}
              error={errors.weekly_budget?.message}
              {...register("weekly_budget")}
            />
            <Controller
              control={control}
              name="noLimit"
              render={({ field }) => (
                <Checkbox
                  checked={field.value}
                  onCheckedChange={field.onChange}
                  label={copy.planning.noLimit}
                />
              )}
            />
          </div>
          <SelectField
            label={copy.planning.serviceLevel}
            hint={copy.planning.serviceLevelHint}
            {...register("service_level")}
          >
            {SERVICE_LEVELS.map((level) => (
              <option key={level} value={level}>
                {Math.round(Number(level) * 100)}%
              </option>
            ))}
          </SelectField>
          <NumberField
            label={copy.planning.review}
            suffix={copy.planning.days}
            decimals={false}
            hint={copy.planning.reviewHint}
            error={errors.review_period_days?.message}
            {...register("review_period_days")}
          />
          <NumberField
            label={copy.planning.leadTime}
            suffix={copy.planning.days}
            decimals={false}
            hint={copy.planning.leadTimeHint}
            error={errors.default_lead_time_days?.message}
            {...register("default_lead_time_days")}
          />
          <NumberField
            label={copy.planning.nearExpiry}
            suffix={copy.planning.days}
            decimals={false}
            error={errors.near_expiry_days?.message}
            {...register("near_expiry_days")}
          />
          <NumberField
            label={copy.planning.nonMoving}
            suffix={copy.planning.days}
            decimals={false}
            error={errors.nonmoving_days?.message}
            {...register("nonmoving_days")}
          />
          <NumberField
            label={copy.planning.slowCover}
            suffix={copy.planning.days}
            decimals={false}
            hint={copy.planning.slowCoverHint}
            error={errors.slow_cover_days?.message}
            {...register("slow_cover_days")}
          />
          <NumberField
            label={copy.planning.excess}
            suffix={copy.planning.days}
            decimals={false}
            hint={copy.planning.excessHint}
            error={errors.excess_horizon_days?.message}
            {...register("excess_horizon_days")}
          />
          <NumberField
            label={copy.planning.staleCount}
            suffix={copy.planning.days}
            decimals={false}
            hint={copy.planning.staleCountHint}
            error={errors.stale_count_days?.message}
            {...register("stale_count_days")}
          />
          <NumberField
            label={copy.planning.shelfLife}
            suffix="%"
            decimals={false}
            hint={copy.planning.shelfLifeHint}
            error={errors.shelf_pct?.message}
            {...register("shelf_pct")}
          />
          <SelectField label={copy.planning.packRounding} {...register("pack_rounding")}>
            <option value="up">{copy.planning.roundUp}</option>
            <option value="nearest_safe">{copy.planning.roundNearest}</option>
          </SelectField>
        </div>
      </Panel>

      <Panel title={copy.planning.weights}>
        <p className="mb-3 text-sm text-text-2">{copy.planning.weightsHint}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ["w_risk", copy.planning.weightRisk],
              ["w_value", copy.planning.weightValue],
              ["w_confidence", copy.planning.weightConfidence],
              ["w_excess", copy.planning.weightExcess],
            ] as const
          ).map(([name, label]) => (
            <Controller
              key={name}
              control={control}
              name={name}
              render={({ field }) => (
                <WeightSlider label={label} value={field.value ?? 0} onChange={field.onChange} />
              )}
            />
          ))}
        </div>
        <p
          className={total === 100 ? "mt-3 text-sm text-text-2" : "mt-3 text-sm text-critical"}
          aria-live="polite"
        >
          {copy.planning.weightsTotal(total)}
          {total !== 100 ? `. ${copy.planning.weightsError}` : ""}
        </p>
      </Panel>

      <Panel>
        <Controller
          control={control}
          name="agents_enabled"
          render={({ field }) => (
            <Switch
              checked={field.value}
              onCheckedChange={field.onChange}
              label={copy.planning.assistant}
              hint={copy.planning.assistantHint}
            />
          )}
        />
      </Panel>

      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary">
          {copy.planning.save}
        </Button>
        {info ? <span className="text-sm text-text-2">{info}</span> : null}
      </div>

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={copy.planning.confirmTitle}
        body={copy.planning.confirmBody}
        confirmLabel={copy.planning.confirmButton}
        loading={save.isPending}
        onConfirm={() => save.mutate(getValues())}
      >
        <ul className="space-y-1 text-base">
          {(confirming ?? []).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </ConfirmDialog>
    </form>
  );
}

// ------------------------------------------------------------------ calendar

function CalendarTab() {
  const today = todayIso();
  const events = useApiQuery<CalendarEvent[]>("/calendar/events", {
    from: addDays(today, -60),
    to: addDays(today, 400),
  });
  const columns: Column<CalendarEvent>[] = [
    {
      key: "name",
      header: copy.calendar.columns.name,
      className: "min-w-48",
      cell: (e) => <span className="font-medium">{e.name}</span>,
    },
    {
      key: "kind",
      header: copy.calendar.columns.kind,
      cell: (e) => copy.calendar.kinds[e.kind as keyof typeof copy.calendar.kinds] ?? e.kind,
    },
    {
      key: "dates",
      header: copy.calendar.columns.dates,
      cell: (e) => dateRange(e.start_date, e.end_date),
    },
    {
      key: "status",
      header: copy.calendar.columns.status,
      cell: (e) =>
        e.is_verified ? (
          <StatusChip tone="ok">{copy.calendar.verified}</StatusChip>
        ) : (
          <StatusChip tone="medium">{copy.calendar.mayShift}</StatusChip>
        ),
    },
    {
      key: "before",
      header: copy.calendar.columns.before,
      numeric: true,
      cell: (e) => e.pre_window_days,
    },
    {
      key: "after",
      header: copy.calendar.columns.after,
      numeric: true,
      cell: (e) => e.post_window_days,
    },
    {
      key: "delay",
      header: copy.calendar.columns.delay,
      unit: common.units.days,
      numeric: true,
      cell: (e) => e.delivery_delay_days,
    },
  ];
  return (
    <>
      <p className="mb-4 max-w-3xl text-base text-text-2">{copy.calendar.intro}</p>
      <DataTable
        caption={copy.tabs.calendar}
        columns={columns}
        rows={events.data}
        rowId={(e) => e.id}
        loading={events.isLoading}
        error={events.isError ? copy.calendar.loadFailed : null}
        onRetry={() => void events.refetch()}
        empty={<EmptyState title={copy.calendar.empty} />}
      />
      <p className="mt-3 text-sm text-text-3">{copy.calendar.readOnlyNote}</p>
    </>
  );
}

// ------------------------------------------------------------------ account

const passwordSchema = z
  .object({
    current_password: z.string().min(1, copy.account.errors.current),
    new_password: z.string().min(12, copy.account.errors.short),
    confirm: z.string(),
  })
  .superRefine((v, ctx) => {
    if (v.confirm !== v.new_password)
      ctx.addIssue({ code: "custom", path: ["confirm"], message: copy.account.errors.mismatch });
    if (v.new_password && v.new_password === v.current_password) {
      ctx.addIssue({ code: "custom", path: ["new_password"], message: copy.account.errors.same });
    }
  });
type PasswordValues = z.infer<typeof passwordSchema>;

function AccountTab() {
  const { user } = useSession();
  const { logoutEverywhere } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema), mode: "onBlur" });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await post("/auth/change-password", {
        current_password: values.current_password,
        new_password: values.new_password,
      });
      notify.success(copy.account.saved);
      reset();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ["new_password", "current_password"]));
    }
  });

  return (
    <div className="max-w-xl space-y-6">
      <Panel>
        <KeyValueList
          rows={[{ label: copy.account.signedInAs, value: `${user.full_name}, ${user.email}` }]}
        />
      </Panel>
      <Panel title={copy.account.changePassword}>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          <TextField
            label={copy.account.current}
            type="password"
            autoComplete="current-password"
            error={errors.current_password?.message}
            {...register("current_password")}
          />
          <TextField
            label={copy.account.next}
            type="password"
            autoComplete="new-password"
            hint={copy.account.rules}
            error={errors.new_password?.message}
            {...register("new_password")}
          />
          <TextField
            label={copy.account.confirm}
            type="password"
            autoComplete="new-password"
            error={errors.confirm?.message}
            {...register("confirm")}
          />
          {formError ? <Banner tone="error">{formError}</Banner> : null}
          <Button type="submit" variant="primary" loading={isSubmitting}>
            {copy.account.save}
          </Button>
        </form>
      </Panel>
      <Panel>
        <p className="mb-3 text-sm text-text-2">{copy.account.signOutEverywhereHint}</p>
        <Button
          variant="destructive"
          loading={signingOut}
          onClick={() => {
            setSigningOut(true);
            void logoutEverywhere().catch((e) => {
              setSigningOut(false);
              notify.error(errorText(e));
            });
          }}
        >
          {copy.account.signOutEverywhere}
        </Button>
      </Panel>
    </div>
  );
}

// ------------------------------------------------------------------ about

type ReportHead = { data_cutoff: string; model_version: string };

function AboutTab() {
  const health = useApiQuery<{ version: string }>("/health");
  const reports = useApiQuery<Page<ReportHead>>("/reports", { page_size: 1 });
  const latest = reports.data?.items[0];
  const { tenant } = useSession();
  return (
    <div className="max-w-2xl space-y-6">
      <Panel>
        <KeyValueList
          rows={[
            { label: copy.about.version, value: health.data?.version ?? "" },
            {
              label: copy.about.cutoff,
              value: latest ? formatDate(latest.data_cutoff) : copy.about.none,
            },
            { label: copy.about.model, value: latest?.model_version ?? "" },
          ].filter((r) => r.value !== "")}
        />
      </Panel>
      {tenant.is_synthetic ? (
        <Panel title={copy.about.demoTitle}>
          <p className="text-base">{copy.about.demo}</p>
        </Panel>
      ) : null}
      <Panel title={copy.about.limitsTitle}>
        <ul className="list-disc space-y-2 pl-5 text-base">
          {copy.about.limits.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

export default function SettingsPage() {
  const [params, setParams] = useQueryParams({ tab: "business" });
  return (
    <>
      <PageHeader title={copy.title} />
      <Tabs
        label={copy.tabsLabel}
        value={params.tab}
        onValueChange={(tab) => setParams({ tab })}
        items={[
          { value: "business", label: copy.tabs.business },
          { value: "planning", label: copy.tabs.planning },
          { value: "calendar", label: copy.tabs.calendar },
          { value: "account", label: copy.tabs.account },
          { value: "about", label: copy.tabs.about },
        ]}
      >
        <TabPanel value="business">
          <BusinessTab />
        </TabPanel>
        <TabPanel value="planning">
          <PlanningTab />
        </TabPanel>
        <TabPanel value="calendar">
          <CalendarTab />
        </TabPanel>
        <TabPanel value="account">
          <AccountTab />
        </TabPanel>
        <TabPanel value="about">
          <AboutTab />
        </TabPanel>
      </Tabs>
    </>
  );
}
