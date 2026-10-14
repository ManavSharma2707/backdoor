import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { toScaled } from "@/lib/decimal";
import { errorText } from "@/lib/forms";
import { newKey } from "@/lib/hooks";
import { useApiQuery } from "@/lib/queries";
import { formatDateTime, money, quantity } from "@/lib/format";
import { common } from "@/copy/common";
import { sales as copy } from "@/copy/sales";
import type { Sale, SaleLine } from "@/types/models";
import { Button } from "@/components/ui/button";
import {
  Banner,
  KeyValueList,
  Mono,
  PageHeader,
  Panel,
  Skeleton,
  StatusChip,
} from "@/components/ui/display";
import { NumberInput, SelectField, TextareaField } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { notify } from "@/components/ui/pickers";
import { DataTable, type Column } from "@/components/ui/table";

type Disposition = "restock" | "damaged" | "expired";

function remaining(line: SaleLine): number {
  return Number(line.quantity) - Number(line.returned_qty);
}

function ReturnDialog({
  sale,
  open,
  onOpenChange,
}: {
  sale: Sale;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const keyRef = useRef(newKey());
  const [entries, setEntries] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [disposition, setDisposition] = useState<Disposition>("restock");
  const [error, setError] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState<string | undefined>();

  useEffect(() => {
    if (open) {
      keyRef.current = newKey();
      setEntries({});
      setReason("");
      setDisposition("restock");
      setError(null);
      setReasonError(undefined);
    }
  }, [open]);

  const save = useMutation({
    mutationFn: (lines: { sale_line_id: number; quantity: string; disposition: Disposition }[]) =>
      post(
        `/sales/${sale.id}/returns`,
        { reason: reason.trim(), lines },
        { idempotencyKey: keyRef.current },
      ),
    onSuccess: () => {
      notify.success(copy.detail.returnSaved);
      onOpenChange(false);
      void queryClient.invalidateQueries();
    },
    onError: (e) => setError(errorText(e)),
  });

  const submit = () => {
    setError(null);
    setReasonError(undefined);
    const lines: { sale_line_id: number; quantity: string; disposition: Disposition }[] = [];
    for (const line of sale.lines) {
      const raw = (entries[line.id] ?? "").trim();
      if (raw === "") continue;
      const asked = toScaled(raw, 3);
      const room = toScaled(String(remaining(line).toFixed(3)), 3);
      if (
        asked === null ||
        asked <= 0n ||
        room === null ||
        asked > room ||
        !/^\d+(\.\d{1,3})?$/.test(raw)
      ) {
        setError(copy.detail.returnQtyInvalid);
        return;
      }
      lines.push({ sale_line_id: line.id, quantity: raw, disposition });
    }
    if (lines.length === 0) {
      setError(copy.detail.returnNothing);
      return;
    }
    if (!reason.trim()) {
      setReasonError(copy.detail.returnReasonRequired);
      return;
    }
    save.mutate(lines);
  };

  const returnable = sale.lines.filter((l) => remaining(l) > 0);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.detail.returnTitle}
      wide
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button variant="primary" loading={save.isPending} onClick={submit}>
            {copy.detail.returnSave}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {returnable.length === 0 ? (
          <p className="text-base">{copy.detail.nothingToReturn}</p>
        ) : null}
        {returnable.map((line) => (
          <div key={line.id} className="grid grid-cols-[minmax(0,1fr)_7rem] items-start gap-3">
            <div className="min-w-0">
              <div className="truncate text-base font-medium">{line.product_name}</div>
              <div className="text-xs text-text-3">
                {copy.detail.returnMax(quantity(remaining(line)))}
              </div>
            </div>
            <NumberInput
              aria-label={copy.detail.returnQty(line.product_name)}
              value={entries[line.id] ?? ""}
              placeholder="0"
              onChange={(e) => setEntries((prev) => ({ ...prev, [line.id]: e.target.value }))}
              className="h-8"
            />
          </div>
        ))}
        <SelectField
          label={copy.detail.returnDisposition}
          value={disposition}
          onChange={(e) => setDisposition(e.target.value as Disposition)}
        >
          <option value="restock">{copy.detail.dispositions.restock}</option>
          <option value="damaged">{copy.detail.dispositions.damaged}</option>
          <option value="expired">{copy.detail.dispositions.expired}</option>
        </SelectField>
        <TextareaField
          label={copy.detail.returnReason}
          value={reason}
          error={reasonError}
          onChange={(e) => setReason(e.target.value)}
        />
        {error ? <Banner tone="error">{error}</Banner> : null}
      </div>
    </Dialog>
  );
}

function VoidDialog({
  sale,
  open,
  onOpenChange,
}: {
  sale: Sale;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [formError, setFormError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setReason("");
      setError(undefined);
      setFormError(null);
    }
  }, [open]);
  const save = useMutation({
    mutationFn: () => post(`/sales/${sale.id}/void`, { reason: reason.trim() }),
    onSuccess: () => {
      notify.success(copy.detail.voidedToast);
      onOpenChange(false);
      void queryClient.invalidateQueries();
    },
    onError: (e) => setFormError(errorText(e)),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.detail.voidTitle(sale.bill_no)}
      description={copy.detail.voidBody}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button
            variant="destructive-filled"
            loading={save.isPending}
            onClick={() => {
              if (!reason.trim()) {
                setError(copy.detail.voidReasonRequired);
                return;
              }
              save.mutate();
            }}
          >
            {copy.detail.void}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextareaField
          label={copy.detail.voidReason}
          value={reason}
          error={error}
          onChange={(e) => setReason(e.target.value)}
        />
        {formError ? <Banner tone="error">{formError}</Banner> : null}
      </div>
    </Dialog>
  );
}

export default function SaleDetailPage() {
  const { id = "" } = useParams();
  const sale = useApiQuery<Sale>(`/sales/${id}`);
  const [returning, setReturning] = useState(false);
  const [voiding, setVoiding] = useState(false);

  if (sale.isLoading) return <Skeleton className="h-64 w-full" />;
  if (sale.isError || !sale.data) return <Banner tone="error">{copy.detail.notFound}</Banner>;
  const s = sale.data;
  const isVoid = s.status === "void";
  const hasReturns = (s.returns ?? []).length > 0;
  const canReturn = !isVoid && s.lines.some((l) => remaining(l) > 0);

  const columns: Column<SaleLine>[] = [
    {
      key: "product",
      header: copy.detail.lines.product,
      className: "min-w-52",
      cell: (l) => (
        <div className="py-1">
          <Link to={`/products/${l.product_id}`} className="font-medium hover:underline">
            {l.product_name}
          </Link>
          <div>
            <Mono className="text-text-3">{l.product_sku}</Mono>
          </div>
        </div>
      ),
    },
    {
      key: "batch",
      header: copy.detail.lines.batch,
      cell: (l) => (l.batch_no ? <Mono>{l.batch_no}</Mono> : ""),
    },
    {
      key: "qty",
      header: copy.detail.lines.quantity,
      numeric: true,
      cell: (l) => quantity(l.quantity),
    },
    {
      key: "returned",
      header: copy.detail.lines.returned,
      numeric: true,
      cell: (l) => (Number(l.returned_qty) > 0 ? quantity(l.returned_qty) : ""),
    },
    {
      key: "price",
      header: copy.detail.lines.price,
      unit: "₹",
      numeric: true,
      cell: (l) => money(l.unit_price, 2).replace("₹", ""),
    },
    {
      key: "discount",
      header: copy.detail.lines.discount,
      unit: "₹",
      numeric: true,
      cell: (l) =>
        Number(l.discount_amount) > 0 ? money(l.discount_amount, 2).replace("₹", "") : "",
    },
    {
      key: "total",
      header: copy.detail.lines.total,
      unit: "₹",
      numeric: true,
      cell: (l) => money(l.line_total, 2).replace("₹", ""),
    },
  ];

  return (
    <>
      <PageHeader
        title={copy.detail.title(s.bill_no)}
        context={copy.detail.context(formatDateTime(s.sold_at), copy.payment[s.payment_mode])}
        actions={
          <>
            <StatusChip tone={isVoid ? "critical" : "ok"}>{copy.status[s.status]}</StatusChip>
            <Button disabled={!canReturn} onClick={() => setReturning(true)}>
              {copy.detail.record}
            </Button>
            <Button
              variant="destructive"
              disabled={isVoid || hasReturns}
              title={hasReturns ? copy.detail.hasReturnsHint : undefined}
              onClick={() => setVoiding(true)}
            >
              {copy.detail.void}
            </Button>
          </>
        }
      />
      {isVoid ? (
        <Banner tone="warning" className="mb-4">
          {s.void_reason ? copy.detail.voidBanner(s.void_reason) : copy.detail.voidBannerNoReason}
        </Banner>
      ) : null}
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <DataTable
          caption={copy.detail.title(s.bill_no)}
          columns={columns}
          rows={s.lines}
          rowId={(l) => String(l.id)}
        />
        <div className="space-y-6">
          <Panel>
            <KeyValueList
              rows={[
                { label: copy.detail.subtotal, value: money(s.subtotal, 2) },
                ...(Number(s.discount_total) > 0
                  ? [{ label: copy.detail.discount, value: money(s.discount_total, 2) }]
                  : []),
                { label: copy.detail.tax, value: money(s.tax_total, 2) },
                {
                  label: copy.detail.total,
                  value: <span className="text-md font-semibold">{money(s.total, 2)}</span>,
                },
              ]}
            />
          </Panel>
          {hasReturns ? (
            <Panel title={copy.detail.returnsTitle}>
              <ul className="space-y-2 text-base">
                {(s.returns ?? []).map((r) => (
                  <li key={r.id}>
                    <div>{copy.detail.returnLine(r.return_no, formatDateTime(r.created_at))}</div>
                    <div className="text-sm text-text-2">
                      {copy.detail.returnRefund(money(r.refund_total, 2))}
                    </div>
                    <div className="text-sm text-text-3">{r.reason}</div>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
      <ReturnDialog sale={s} open={returning} onOpenChange={setReturning} />
      <VoidDialog sale={s} open={voiding} onOpenChange={setVoiding} />
    </>
  );
}
