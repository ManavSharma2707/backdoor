import { useCallback, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { errorText } from "@/lib/forms";
import { useQueryParams } from "@/lib/hooks";
import { useCategories, useListQuery } from "@/lib/queries";
import {
  compactMoney,
  formatDate,
  formatDateTime,
  money,
  quantity,
  signedQuantity,
} from "@/lib/format";
import { stock as copy } from "@/copy/stock";
import { common } from "@/copy/common";
import type { BatchRow, MovementRow, StockRow } from "@/types/models";
import { SearchBox } from "@/components/search-box";
import { Button, TextButton } from "@/components/ui/button";
import { Segmented, TabPanel, Tabs } from "@/components/ui/controls";
import { EmptyState, Mono, PageHeader, StatusChip, type Tone } from "@/components/ui/display";
import { Select, SelectField, TextareaField } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { DateField, notify } from "@/components/ui/pickers";
import { DataTable, Pagination, type Column } from "@/components/ui/table";
import { AdjustmentDialog } from "./adjustment-dialog";
import { CountsTab } from "./counts";
import { OutOfStockTab } from "./out-of-stock";

const STATUS_TONE: Record<string, Tone> = {
  out: "critical",
  low: "high",
  ok: "ok",
  expired: "critical",
};

function LevelsTab() {
  const [params, setParams] = useQueryParams({
    q: "",
    category_id: "",
    status: "",
    page: "1",
    page_size: "50",
  });
  const categories = useCategories();
  const list = useListQuery<StockRow>("/inventory/stock", { ...params });
  const setQ = useCallback((q: string) => setParams({ q }), [setParams]);

  const columns: Column<StockRow>[] = [
    {
      key: "product",
      header: copy.levels.columns.product,
      className: "min-w-56",
      cell: (r) => (
        <div className="py-1">
          <Link to={`/products/${r.product_id}`} className="font-medium hover:underline">
            {r.name}
          </Link>
          <div>
            <Mono className="text-text-3">{r.sku}</Mono>
          </div>
        </div>
      ),
    },
    {
      key: "onHand",
      header: copy.levels.columns.onHand,
      numeric: true,
      cell: (r) => quantity(r.on_hand),
    },
    {
      key: "sellable",
      header: copy.levels.columns.sellable,
      numeric: true,
      cell: (r) => quantity(r.sellable),
    },
    {
      key: "incoming",
      header: copy.levels.columns.incoming,
      numeric: true,
      cell: (r) => (
        <span>
          {quantity(r.incoming)}
          {Number(r.incoming_overdue) > 0 ? (
            <span className="block text-xs text-high">
              {copy.levels.overdueIncoming(quantity(r.incoming_overdue))}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "cover",
      header: copy.levels.columns.cover,
      numeric: true,
      cell: (r) => (r.days_of_cover ? quantity(r.days_of_cover) : ""),
    },
    {
      key: "value",
      header: copy.levels.columns.value,
      unit: "₹",
      numeric: true,
      cell: (r) => money(r.value).replace("₹", ""),
    },
    {
      key: "status",
      header: copy.levels.columns.status,
      cell: (r) => (
        <StatusChip tone={STATUS_TONE[r.status] ?? "neutral"}>
          {copy.levels.status[r.status as keyof typeof copy.levels.status]}
        </StatusChip>
      ),
    },
    {
      key: "count",
      header: copy.levels.columns.lastCount,
      cell: (r) => (r.last_count_date ? formatDate(r.last_count_date) : copy.levels.notCounted),
    },
  ];

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchBox
          value={params.q}
          onChange={setQ}
          label={copy.searchLabel}
          placeholder={copy.searchPlaceholder}
        />
        <div className="w-full sm:w-52">
          <Select
            aria-label={copy.levels.category}
            value={params.category_id}
            onChange={(e) => setParams({ category_id: e.target.value })}
          >
            <option value="">{copy.levels.allCategories}</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-48">
          <Select
            aria-label={copy.levels.statusLabel}
            value={params.status}
            onChange={(e) => setParams({ status: e.target.value })}
          >
            <option value="">{copy.levels.allStatuses}</option>
            {(["out", "low", "ok", "expired"] as const).map((s) => (
              <option key={s} value={s}>
                {copy.levels.status[s]}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <DataTable
        caption={copy.tabs.levels}
        columns={columns}
        rows={list.data?.items}
        rowId={(r) => r.product_id}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={copy.levels.empty} hint={copy.levels.emptyHint} />}
        footer={
          list.data ? (
            <Pagination
              page={Number(params.page)}
              pageSize={Number(params.page_size)}
              total={list.data.total}
              onPageChange={(page) => setParams({ page: String(page) }, { keepPage: true })}
              onPageSizeChange={(size) => setParams({ page_size: String(size) })}
            />
          ) : null
        }
      />
    </>
  );
}

function WriteOffDialog({ batch, onClose }: { batch: BatchRow | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState<"expired" | "damaged">("expired");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: (id: string) =>
      post(`/inventory/batches/${id}/write-off`, { reason, note: note || undefined }),
    onSuccess: () => {
      notify.success(copy.batches.writtenOff);
      void queryClient.invalidateQueries();
      onClose();
    },
    onError: (error) => notify.error(errorText(error)),
  });
  return (
    <Dialog
      open={Boolean(batch)}
      onOpenChange={(open) => !open && onClose()}
      title={batch ? copy.batches.writeOffTitle(batch.batch_no) : ""}
      description={
        batch ? copy.batches.writeOffBody(quantity(batch.on_hand), batch.name) : undefined
      }
      footer={
        <>
          <Button onClick={onClose}>{common.cancel}</Button>
          <Button
            variant="destructive-filled"
            loading={save.isPending}
            onClick={() => batch && save.mutate(batch.batch_id)}
          >
            {copy.batches.writeOff}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <SelectField
          label={copy.batches.writeOffReason}
          value={reason}
          onChange={(e) => setReason(e.target.value as "expired" | "damaged")}
        >
          <option value="expired">{copy.batches.reasonExpired}</option>
          <option value="damaged">{copy.batches.reasonDamaged}</option>
        </SelectField>
        <TextareaField
          label={copy.batches.writeOffNote}
          optional
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>
    </Dialog>
  );
}

function BatchesTab() {
  const [params, setParams] = useQueryParams({ window: "90", q: "", page: "1", page_size: "50" });
  const [writing, setWriting] = useState<BatchRow | null>(null);
  const setQ = useCallback((q: string) => setParams({ q }), [setParams]);
  const query: Record<string, string | boolean | undefined> = {
    page: params.page,
    page_size: params.page_size,
    expired: params.window === "expired" ? true : undefined,
    expiring_within_days: /^\d+$/.test(params.window) ? params.window : undefined,
  };
  const list = useListQuery<BatchRow>("/inventory/batches", query as Record<string, string>);
  const rows = (list.data?.items ?? []).filter(
    (b) =>
      !params.q ||
      b.name.toLowerCase().includes(params.q.toLowerCase()) ||
      b.sku.toLowerCase().includes(params.q.toLowerCase()),
  );
  const totalValue = rows.reduce((sum, b) => sum + Number(b.value), 0);

  const columns: Column<BatchRow>[] = [
    {
      key: "product",
      header: copy.batches.columns.product,
      className: "min-w-52",
      cell: (b) => (
        <div className="py-1">
          <Link to={`/products/${b.product_id}`} className="font-medium hover:underline">
            {b.name}
          </Link>
          <div>
            <Mono className="text-text-3">{b.sku}</Mono>
          </div>
        </div>
      ),
    },
    { key: "batch", header: copy.batches.columns.batch, cell: (b) => <Mono>{b.batch_no}</Mono> },
    { key: "expiry", header: copy.batches.columns.expiry, cell: (b) => formatDate(b.expiry_date) },
    {
      key: "days",
      header: copy.batches.columns.daysLeft,
      numeric: true,
      cell: (b) => (
        <span
          className={
            b.is_expired
              ? "font-medium text-critical"
              : b.days_to_expiry <= 30
                ? "text-high"
                : undefined
          }
        >
          {copy.batches.daysLeft(b.days_to_expiry)}
        </span>
      ),
    },
    {
      key: "qty",
      header: copy.batches.columns.quantity,
      numeric: true,
      cell: (b) => quantity(b.on_hand),
    },
    {
      key: "value",
      header: copy.batches.columns.value,
      unit: "₹",
      numeric: true,
      cell: (b) => money(b.value).replace("₹", ""),
    },
    {
      key: "first",
      header: copy.batches.columns.sellFirst,
      cell: (b) =>
        b.sell_first ? <StatusChip tone="info">{copy.batches.sellFirst}</StatusChip> : null,
    },
    {
      key: "actions",
      header: copy.batches.columns.actions,
      headerHidden: true,
      cell: (b) =>
        b.is_expired ? (
          <TextButton onClick={() => setWriting(b)}>{copy.batches.writeOff}</TextButton>
        ) : null,
    },
  ];

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchBox
          value={params.q}
          onChange={setQ}
          label={copy.searchLabel}
          placeholder={copy.searchPlaceholder}
        />
        <Segmented
          label={copy.batches.window}
          value={params.window}
          onValueChange={(window) => setParams({ window })}
          options={[
            { value: "expired", label: copy.batches.windows.expired },
            { value: "30", label: copy.batches.windows["30"] },
            { value: "60", label: copy.batches.windows["60"] },
            { value: "90", label: copy.batches.windows["90"] },
            { value: "all", label: copy.batches.windows.all },
          ]}
        />
      </div>
      <DataTable
        caption={copy.tabs.batches}
        columns={columns}
        rows={rows}
        rowId={(b) => b.batch_id}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={copy.batches.empty} hint={copy.batches.emptyHint} />}
        footer={
          list.data ? (
            <>
              <p className="border-t border-border px-3 py-2 text-sm text-text-2">
                {copy.batches.total(compactMoney(totalValue), rows.length)}
              </p>
              <Pagination
                page={Number(params.page)}
                pageSize={Number(params.page_size)}
                total={list.data.total}
                onPageChange={(page) => setParams({ page: String(page) }, { keepPage: true })}
                onPageSizeChange={(size) => setParams({ page_size: String(size) })}
              />
            </>
          ) : null
        }
      />
      <WriteOffDialog batch={writing} onClose={() => setWriting(null)} />
    </>
  );
}

const MOVEMENT_TYPES = Object.keys(copy.movements.types) as (keyof typeof copy.movements.types)[];

function MovementsTab() {
  const [params, setParams] = useQueryParams({
    type: "",
    from: "",
    to: "",
    page: "1",
    page_size: "50",
  });
  const list = useListQuery<MovementRow>("/inventory/movements", { ...params });
  const columns: Column<MovementRow>[] = [
    {
      key: "when",
      header: copy.movements.columns.when,
      cell: (m) => formatDateTime(m.occurred_at),
    },
    {
      key: "product",
      header: copy.movements.columns.product,
      className: "min-w-52",
      cell: (m) => (
        <div className="py-1">
          <Link to={`/products/${m.product_id}`} className="hover:underline">
            {m.name}
          </Link>
          <div>
            <Mono className="text-text-3">{m.sku}</Mono>
          </div>
        </div>
      ),
    },
    {
      key: "batch",
      header: copy.movements.columns.batch,
      cell: (m) => (m.batch_no ? <Mono>{m.batch_no}</Mono> : ""),
    },
    {
      key: "type",
      header: copy.movements.columns.type,
      cell: (m) => copy.movements.types[m.movement_type],
    },
    {
      key: "change",
      header: copy.movements.columns.change,
      numeric: true,
      cell: (m) => signedQuantity(m.quantity_delta),
    },
    {
      key: "reason",
      header: copy.movements.columns.reason,
      cell: (m) => m.note ?? m.reason_code ?? "",
    },
    { key: "by", header: copy.movements.columns.by, cell: (m) => m.created_by_name ?? "" },
  ];
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-52">
          <Select
            aria-label={copy.movements.type}
            value={params.type}
            onChange={(e) => setParams({ type: e.target.value })}
          >
            <option value="">{copy.movements.allTypes}</option>
            {MOVEMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {copy.movements.types[t]}
              </option>
            ))}
          </Select>
        </div>
        <DateField
          label={copy.movements.from}
          value={params.from}
          onChange={(from) => setParams({ from })}
          className="w-44"
        />
        <DateField
          label={copy.movements.to}
          value={params.to}
          onChange={(to) => setParams({ to })}
          className="w-44"
        />
      </div>
      <DataTable
        caption={copy.tabs.movements}
        columns={columns}
        rows={list.data?.items}
        rowId={(m) => String(m.id)}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={copy.movements.empty} hint={copy.movements.emptyHint} />}
        footer={
          list.data ? (
            <Pagination
              page={Number(params.page)}
              pageSize={Number(params.page_size)}
              total={list.data.total}
              onPageChange={(page) => setParams({ page: String(page) }, { keepPage: true })}
              onPageSizeChange={(size) => setParams({ page_size: String(size) })}
            />
          ) : null
        }
      />
    </>
  );
}

export default function StockPage() {
  const { tenant } = useSession();
  const [params, setParams] = useQueryParams({
    tab: tenant.business_type === "medical" ? "batches" : "levels",
  });
  const [adjusting, setAdjusting] = useState(false);
  const [starting, setStarting] = useState(false);

  return (
    <>
      <PageHeader
        title={copy.title}
        actions={
          <>
            <Button
              onClick={() => {
                setParams({ tab: "counts" });
                setStarting(true);
              }}
            >
              {copy.startCount}
            </Button>
            <Button variant="primary" onClick={() => setAdjusting(true)}>
              {copy.recordAdjustment}
            </Button>
          </>
        }
      />
      <Tabs
        label={copy.tabsLabel}
        value={params.tab}
        onValueChange={(tab) => setParams({ tab })}
        items={[
          { value: "levels", label: copy.tabs.levels },
          { value: "batches", label: copy.tabs.batches },
          { value: "movements", label: copy.tabs.movements },
          { value: "counts", label: copy.tabs.counts },
          { value: "out", label: copy.tabs.outOfStock },
        ]}
      >
        <TabPanel value="levels">
          <LevelsTab />
        </TabPanel>
        <TabPanel value="batches">
          <BatchesTab />
        </TabPanel>
        <TabPanel value="movements">
          <MovementsTab />
        </TabPanel>
        <TabPanel value="counts">
          <CountsTab
            startOpen={starting}
            onStartClose={() => setStarting(false)}
            onStartRequest={() => setStarting(true)}
          />
        </TabPanel>
        <TabPanel value="out">
          <OutOfStockTab />
        </TabPanel>
      </Tabs>
      <AdjustmentDialog open={adjusting} onOpenChange={setAdjusting} />
    </>
  );
}
