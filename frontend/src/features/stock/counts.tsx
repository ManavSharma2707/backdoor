import { useEffect, useState } from "react";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { patch, post } from "@/lib/api";
import { errorText, isDecimal } from "@/lib/forms";
import { useQueryParams } from "@/lib/hooks";
import { useApiQuery, useCategories, useListQuery } from "@/lib/queries";
import { formatDate, money, quantity, signedQuantity } from "@/lib/format";
import { common } from "@/copy/common";
import { stock as copy } from "@/copy/stock";
import type { Count, CountListItem } from "@/types/models";
import { Button, TextButton } from "@/components/ui/button";
import { Banner, EmptyState, Mono, Skeleton, StatusChip } from "@/components/ui/display";
import { NumberInput, SelectField, TextareaField } from "@/components/ui/field";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { notify } from "@/components/ui/pickers";
import { DataTable, Pagination, type Column } from "@/components/ui/table";

function StartDialog({
  open,
  onOpenChange,
  onStarted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const categories = useCategories();
  const [scope, setScope] = useState<"all" | "category">("all");
  const [categoryId, setCategoryId] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () =>
      post<Count>("/inventory/counts", {
        scope,
        category_id: scope === "category" ? categoryId : undefined,
        note: note || undefined,
      }),
    onSuccess: (count) => {
      notify.success(copy.counts.started);
      void queryClient.invalidateQueries({ queryKey: ["/inventory/counts"] });
      onOpenChange(false);
      onStarted(count.id);
    },
    onError: (e) => setError(errorText(e)),
  });
  useEffect(() => {
    if (open) setError(null);
  }, [open]);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.counts.startTitle}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button
            variant="primary"
            loading={start.isPending}
            disabled={scope === "category" && !categoryId}
            onClick={() => start.mutate()}
          >
            {copy.counts.start}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <SelectField
          label={copy.counts.scope}
          value={scope}
          onChange={(e) => setScope(e.target.value as "all" | "category")}
        >
          <option value="all">{copy.counts.scopeAll}</option>
          <option value="category">{copy.counts.scopeCategory}</option>
        </SelectField>
        {scope === "category" ? (
          <SelectField
            label={copy.levels.category}
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            <option value="">{copy.levels.allCategories}</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
        ) : null}
        <TextareaField
          label={copy.counts.note}
          optional
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        {error ? <Banner tone="error">{error}</Banner> : null}
      </div>
    </Dialog>
  );
}

function CountSheet({ id, onBack }: { id: string; onBack: () => void }) {
  const queryClient = useQueryClient();
  const count = useApiQuery<Count>(`/inventory/counts/${id}`);
  const [entries, setEntries] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [bad, setBad] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (count.data) {
      setEntries(
        Object.fromEntries(
          count.data.lines.map((l) => [
            l.id,
            l.counted_qty === null ? "" : String(Number(l.counted_qty)),
          ]),
        ),
      );
    }
  }, [count.data]);

  const draft = count.data?.status === "draft";

  const saveLines = async () => {
    const invalid: Record<string, boolean> = {};
    const lines = Object.entries(entries).map(([line_id, value]) => {
      if (value.trim() !== "" && !isDecimal(value, 3)) invalid[line_id] = true;
      return { line_id, counted_qty: value.trim() === "" ? null : value.trim() };
    });
    setBad(invalid);
    if (Object.keys(invalid).length > 0) throw new Error(copy.counts.invalidQty);
    await patch(`/inventory/counts/${id}/lines`, { lines });
  };

  const save = useMutation({
    mutationFn: saveLines,
    onSuccess: () => {
      notify.success(copy.counts.draftSaved);
      void queryClient.invalidateQueries({ queryKey: [`/inventory/counts/${id}`] });
    },
    onError: (e) => notify.error(errorText(e)),
  });

  const post_ = useMutation({
    mutationFn: async () => {
      await saveLines();
      return post<Count>(`/inventory/counts/${id}/post`);
    },
    onSuccess: () => {
      notify.success(copy.counts.posted);
      setConfirming(false);
      void queryClient.invalidateQueries();
    },
    onError: (e) => {
      setConfirming(false);
      notify.error(errorText(e));
    },
  });

  if (count.isLoading) return <Skeleton className="h-64 w-full" />;
  if (count.isError || !count.data) return <Banner tone="error">{copy.counts.loadFailed}</Banner>;
  const c = count.data;

  const diffFor = (line: Count["lines"][number]): number | null => {
    const raw = entries[line.id];
    if (raw === undefined || raw.trim() === "" || !isDecimal(raw, 3)) return null;
    return Number(raw) - Number(line.system_qty);
  };
  const differing = c.lines.filter((l) => {
    const d = draft ? diffFor(l) : l.variance === null ? null : Number(l.variance);
    return d !== null && d !== 0;
  });

  const columns: Column<Count["lines"][number]>[] = [
    {
      key: "product",
      header: copy.counts.sheetColumns.product,
      className: "min-w-52",
      cell: (l) => (
        <div className="py-1">
          <div className="font-medium">{l.name}</div>
          <Mono className="text-text-3">{l.sku}</Mono>
        </div>
      ),
    },
    {
      key: "batch",
      header: copy.counts.sheetColumns.batch,
      cell: (l) => (l.batch_no ? <Mono>{l.batch_no}</Mono> : ""),
    },
    {
      key: "system",
      header: copy.counts.sheetColumns.system,
      numeric: true,
      cell: (l) => quantity(l.system_qty),
    },
    {
      key: "counted",
      header: copy.counts.sheetColumns.counted,
      numeric: true,
      className: "w-36",
      cell: (l) =>
        draft ? (
          <NumberInput
            aria-label={copy.counts.countedLabel(l.name)}
            aria-invalid={bad[l.id] ? true : undefined}
            value={entries[l.id] ?? ""}
            onChange={(e) => setEntries((prev) => ({ ...prev, [l.id]: e.target.value }))}
            className="h-8"
          />
        ) : l.counted_qty === null ? (
          copy.counts.notCounted
        ) : (
          quantity(l.counted_qty)
        ),
    },
    {
      key: "diff",
      header: copy.counts.sheetColumns.difference,
      numeric: true,
      cell: (l) => {
        const d = draft ? diffFor(l) : l.variance === null ? null : Number(l.variance);
        return d === null ? (
          ""
        ) : (
          <span className={d === 0 ? undefined : "font-medium text-high"}>{signedQuantity(d)}</span>
        );
      },
    },
  ];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <TextButton onClick={onBack}>{copy.counts.backToList}</TextButton>
          <h2 className="text-lg font-semibold">
            {copy.counts.sheetTitle(formatDate(c.count_date))}
          </h2>
          {!draft ? <p className="text-sm text-text-2">{copy.counts.postedNote}</p> : null}
        </div>
        {draft ? (
          <div className="flex gap-2">
            <Button loading={save.isPending} onClick={() => save.mutate()}>
              {copy.counts.saveDraft}
            </Button>
            <Button variant="primary" onClick={() => setConfirming(true)}>
              {copy.counts.post}
            </Button>
          </div>
        ) : (
          <StatusChip tone="ok">{copy.counts.status.posted}</StatusChip>
        )}
      </div>
      <DataTable
        caption={copy.counts.sheetTitle(formatDate(c.count_date))}
        columns={columns}
        rows={c.lines}
        rowId={(l) => l.id}
        skeletonRows={6}
      />
      {!draft ? (
        <p className="mt-3 text-sm text-text-2">
          {copy.counts.differenceTotal(money(c.variance_value))}
        </p>
      ) : null}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={copy.counts.postTitle}
        body={
          differing.length === 0
            ? copy.counts.postBodyNone
            : copy.counts.postBody(differing.length, money(c.variance_value))
        }
        confirmLabel={copy.counts.post}
        loading={post_.isPending}
        onConfirm={() => post_.mutate()}
      />
    </div>
  );
}

export function CountsTab({
  startOpen,
  onStartClose,
}: {
  startOpen: boolean;
  onStartClose: () => void;
  onStartRequest: () => void;
}) {
  const [params, setParams] = useQueryParams({ count: "", page: "1", page_size: "25" });
  const list = useListQuery<CountListItem>("/inventory/counts", {
    page: params.page,
    page_size: params.page_size,
  });

  const columns: Column<CountListItem>[] = [
    {
      key: "date",
      header: copy.counts.columns.date,
      cell: (c) => (
        <TextButton onClick={() => setParams({ count: c.id })}>
          {formatDate(c.count_date)}
        </TextButton>
      ),
    },
    {
      key: "status",
      header: copy.counts.columns.status,
      cell: (c) => (
        <StatusChip tone={c.status === "posted" ? "ok" : "neutral"}>
          {copy.counts.status[c.status]}
        </StatusChip>
      ),
    },
    {
      key: "lines",
      header: copy.counts.columns.lines,
      numeric: true,
      cell: (c) => quantity(c.lines),
    },
    {
      key: "counted",
      header: copy.counts.columns.counted,
      numeric: true,
      cell: (c) => quantity(c.counted_lines),
    },
    { key: "note", header: copy.counts.columns.note, cell: (c) => c.note ?? "" },
  ];
  return (
    <>
      {params.count ? (
        <CountSheet id={params.count} onBack={() => setParams({ count: null })} />
      ) : (
        <DataTable
          caption={copy.counts.list}
          columns={columns}
          rows={list.data?.items}
          rowId={(c) => c.id}
          loading={list.isLoading}
          error={list.isError ? copy.loadFailed : null}
          onRetry={() => void list.refetch()}
          empty={<EmptyState title={copy.counts.empty} hint={copy.counts.emptyHint} />}
          footer={
            list.data ? (
              <Pagination
                page={Number(params.page)}
                pageSize={Number(params.page_size)}
                total={list.data.total}
                onPageChange={(page) => setParams({ page: String(page) }, { keepPage: true })}
              />
            ) : null
          }
        />
      )}
      <StartDialog
        open={startOpen}
        onOpenChange={(open) => !open && onStartClose()}
        onStarted={(id) => setParams({ count: id })}
      />
    </>
  );
}
