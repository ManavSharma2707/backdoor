import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { errorText } from "@/lib/forms";
import { useListQuery } from "@/lib/queries";
import { formatDate } from "@/lib/format";
import { common } from "@/copy/common";
import { stock as copy } from "@/copy/stock";
import type { Product, Stockout } from "@/types/models";
import { ProductPicker } from "@/components/product-search";
import { Button } from "@/components/ui/button";
import { Banner, EmptyState, Mono, StatusChip } from "@/components/ui/display";
import { Field, TextareaField } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { DateField, notify } from "@/components/ui/pickers";
import { DataTable, Pagination, type Column } from "@/components/ui/table";

type FormErrors = { product?: string; from?: string; to?: string };

function AddDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [product, setProduct] = useState<Product | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      post("/inventory/stockouts", {
        product_id: product?.id,
        start_date: from,
        end_date: to || undefined,
        note: note || undefined,
      }),
    onSuccess: () => {
      notify.success(copy.outOfStock.saved);
      void queryClient.invalidateQueries({ queryKey: ["/inventory/stockouts"] });
      setProduct(null);
      setFrom("");
      setTo("");
      setNote("");
      onOpenChange(false);
    },
    onError: (error) => setFormError(errorText(error)),
  });

  const submit = () => {
    const next: FormErrors = {};
    if (!product) next.product = copy.outOfStock.errors.product;
    if (!from) next.from = copy.outOfStock.errors.from;
    if (from && to && to < from) next.to = copy.outOfStock.errors.order;
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length === 0) save.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.outOfStock.dialogTitle}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button variant="primary" loading={save.isPending} onClick={submit}>
            {copy.outOfStock.save}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={copy.outOfStock.product} error={errors.product}>
          {(ids) => (
            <ProductPicker
              {...ids}
              value={product}
              onChange={setProduct}
              placeholder={copy.outOfStock.pickProduct}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <DateField
            label={copy.outOfStock.from}
            value={from}
            onChange={setFrom}
            error={errors.from}
          />
          <DateField
            label={copy.outOfStock.to}
            value={to}
            onChange={setTo}
            optional
            hint={copy.outOfStock.toHint}
            error={errors.to}
          />
        </div>
        <TextareaField
          label={copy.outOfStock.note}
          optional
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        {formError ? <Banner tone="error">{formError}</Banner> : null}
      </div>
    </Dialog>
  );
}

export function OutOfStockTab() {
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const list = useListQuery<Stockout>("/inventory/stockouts", { page, page_size: 50 });
  const columns: Column<Stockout>[] = [
    {
      key: "product",
      header: copy.outOfStock.columns.product,
      className: "min-w-52",
      cell: (s) => (
        <div className="py-1">
          <div className="font-medium">{s.name}</div>
          <Mono className="text-text-3">{s.sku}</Mono>
        </div>
      ),
    },
    { key: "from", header: copy.outOfStock.columns.from, cell: (s) => formatDate(s.start_date) },
    {
      key: "to",
      header: copy.outOfStock.columns.to,
      cell: (s) => (s.end_date ? formatDate(s.end_date) : copy.outOfStock.ongoing),
    },
    {
      key: "source",
      header: copy.outOfStock.columns.source,
      cell: (s) => (
        <StatusChip tone={s.source === "recorded" ? "info" : "neutral"}>
          {copy.outOfStock.source[s.source]}
        </StatusChip>
      ),
    },
    { key: "note", header: copy.outOfStock.columns.note, cell: (s) => s.note ?? "" },
  ];
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-base text-text-2">{copy.outOfStock.intro}</p>
        <Button onClick={() => setAdding(true)}>{copy.outOfStock.add}</Button>
      </div>
      <DataTable
        caption={copy.tabs.outOfStock}
        columns={columns}
        rows={list.data?.items}
        rowId={(s) => s.id}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        empty={<EmptyState title={copy.outOfStock.empty} hint={copy.outOfStock.emptyHint} />}
        footer={
          list.data ? (
            <Pagination page={page} pageSize={50} total={list.data.total} onPageChange={setPage} />
          ) : null
        }
      />
      <AddDialog open={adding} onOpenChange={setAdding} />
    </>
  );
}
