import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api";
import { errorText, isDecimal, toNumber } from "@/lib/forms";
import { newKey } from "@/lib/hooks";
import { addDays, quantity, todayIso } from "@/lib/format";
import { common } from "@/copy/common";
import { purchases as copy } from "@/copy/purchases";
import type { Product, PurchaseOrder, Receipt } from "@/types/models";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/controls";
import { Banner, Mono } from "@/components/ui/display";
import { NumberInput, TextareaField, TextField, Input, Field } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { DateField, DatePicker, notify } from "@/components/ui/pickers";

type Row = { quantity: string; cost: string; batchNo: string; expiry: string; mrp: string };
type RowErrors = Partial<Record<keyof Row, string>>;

export function ReceiptDialog({
  order,
  open,
  onOpenChange,
  onReceived,
}: {
  order: PurchaseOrder;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReceived: (receipt: Receipt) => void;
}) {
  const queryClient = useQueryClient();
  const keyRef = useRef(newKey());
  const openLines = useMemo(
    () => order.lines.filter((l) => Number(l.quantity_open) > 0),
    [order.lines],
  );

  // Whether a product is batch tracked is on the product, not on the order line.
  const products = useQueries({
    queries: openLines.map((l) => ({
      queryKey: [`/products/${l.product_id}`, {}],
      queryFn: () => get<Product>(`/products/${l.product_id}`),
      enabled: open,
      staleTime: 60_000,
    })),
  });
  const tracked = (index: number) => Boolean(products[index]?.data?.is_batch_tracked);

  const [receivedOn, setReceivedOn] = useState(todayIso());
  const [invoiceNo, setInvoiceNo] = useState("");
  const [invoiceTotal, setInvoiceTotal] = useState("");
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [exception, setException] = useState(false);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, RowErrors>>({});
  const [topErrors, setTopErrors] = useState<{ note?: string; invoice?: string; date?: string }>(
    {},
  );
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    keyRef.current = newKey();
    setReceivedOn(todayIso());
    setInvoiceNo("");
    setInvoiceTotal("");
    setException(false);
    setNote("");
    setErrors({});
    setTopErrors({});
    setFormError(null);
    setRows(
      Object.fromEntries(
        openLines.map((l) => [
          l.id,
          {
            quantity: String(Number(l.quantity_open)),
            cost: String(Number(l.unit_cost)),
            batchNo: "",
            expiry: "",
            mrp: "",
          },
        ]),
      ),
    );
  }, [open, openLines]);

  const setRow = (id: string, patch: Partial<Row>) =>
    setRows((current) => ({ ...current, [id]: { ...current[id], ...patch } as Row }));

  const overReceived = openLines.some((l) => {
    const q = rows[l.id]?.quantity ?? "";
    return isDecimal(q, 3) && toNumber(q) > Number(l.quantity_open);
  });
  const openTotal = openLines.reduce((sum, l) => sum + Number(l.quantity_open), 0);

  const save = useMutation({
    mutationFn: () => {
      const lines = openLines
        .map((l, index) => ({ l, index, row: rows[l.id] as Row }))
        .filter(({ row }) => toNumber(row.quantity) > 0)
        .map(({ l, index, row }) => ({
          po_line_id: l.id,
          quantity_received: row.quantity,
          unit_cost: row.cost,
          ...(tracked(index)
            ? { batch_no: row.batchNo.trim(), expiry_date: row.expiry, mrp: row.mrp }
            : {}),
        }));
      return post<Receipt>(
        `/purchase-orders/${order.id}/receipts`,
        {
          received_on: receivedOn,
          invoice_no: invoiceNo.trim() || undefined,
          invoice_total: invoiceTotal.trim() || undefined,
          is_exception: exception || undefined,
          exception_note: exception ? note.trim() : undefined,
          lines,
        },
        { idempotencyKey: keyRef.current },
      );
    },
    onSuccess: (receipt) => {
      notify.success(copy.receipt.saved);
      void queryClient.invalidateQueries();
      onReceived(receipt);
      onOpenChange(false);
    },
    onError: (error) => setFormError(errorText(error)),
  });

  const submit = () => {
    setFormError(null);
    const rowErrors: Record<string, RowErrors> = {};
    const top: typeof topErrors = {};
    let any = false;
    if (!receivedOn) top.date = copy.receipt.errors.date;
    if (invoiceTotal.trim() && !isDecimal(invoiceTotal, 2))
      top.invoice = copy.receipt.errors.invoiceTotal;
    if (overReceived && exception && !note.trim()) top.note = copy.receipt.errors.note;
    openLines.forEach((l, index) => {
      const row = rows[l.id];
      if (!row) return;
      const e: RowErrors = {};
      if (!isDecimal(row.quantity, 3)) e.quantity = copy.receipt.errors.quantity;
      else if (toNumber(row.quantity) > 0) {
        any = true;
        if (!isDecimal(row.cost, 4)) e.cost = copy.receipt.errors.cost;
        if (tracked(index)) {
          if (!row.batchNo.trim()) e.batchNo = copy.receipt.errors.batch;
          if (!row.expiry || row.expiry <= receivedOn) e.expiry = copy.receipt.errors.expiry;
          if (!isDecimal(row.mrp, 2)) e.mrp = copy.receipt.errors.mrp;
        }
      }
      if (Object.keys(e).length) rowErrors[l.id] = e;
    });
    setErrors(rowErrors);
    setTopErrors(top);
    if (!any && Object.keys(rowErrors).length === 0) {
      setFormError(copy.receipt.errors.nothing);
      return;
    }
    if (Object.keys(rowErrors).length || Object.keys(top).length) return;
    save.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.receipt.title}
      description={copy.receipt.leaveEmpty}
      wide
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button variant="primary" loading={save.isPending} onClick={submit}>
            {copy.receipt.save}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <DateField
            label={copy.receipt.receivedOn}
            value={receivedOn}
            onChange={setReceivedOn}
            error={topErrors.date}
            max={addDays(todayIso(), 0)}
          />
          <TextField
            label={copy.receipt.invoiceNo}
            optional
            value={invoiceNo}
            onChange={(e) => setInvoiceNo(e.target.value)}
          />
          <Field label={copy.receipt.invoiceTotal} optional error={topErrors.invoice}>
            {(ids) => (
              <NumberInput
                {...ids}
                suffix="₹"
                value={invoiceTotal}
                onChange={(e) => setInvoiceTotal(e.target.value)}
              />
            )}
          </Field>
        </div>

        <ul className="divide-y divide-border rounded-md border border-border">
          {openLines.map((l, index) => {
            const row = rows[l.id];
            if (!row) return null;
            const e = errors[l.id] ?? {};
            const orderCost = Number(l.unit_cost);
            const newCost = toNumber(row.cost);
            const changed =
              orderCost > 0 && isDecimal(row.cost, 4)
                ? Math.abs(newCost - orderCost) / orderCost
                : 0;
            return (
              <li key={l.id} className="space-y-3 p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <div className="text-base font-medium">{l.product_name}</div>
                    <Mono className="text-text-3">{l.product_sku}</Mono>
                  </div>
                  <div className="text-xs text-text-3">
                    {copy.receipt.columns.open}: {quantity(l.quantity_open)}
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label={copy.receipt.columns.quantity} error={e.quantity}>
                    {(ids) => (
                      <NumberInput
                        {...ids}
                        aria-label={copy.receipt.quantityLabel(l.product_name)}
                        value={row.quantity}
                        onChange={(ev) => setRow(l.id, { quantity: ev.target.value })}
                      />
                    )}
                  </Field>
                  <Field
                    label={copy.receipt.columns.cost}
                    error={e.cost}
                    hint={
                      changed > 0.1
                        ? copy.receipt.costChanged(`${Math.round(changed * 100)}%`)
                        : undefined
                    }
                  >
                    {(ids) => (
                      <NumberInput
                        {...ids}
                        suffix="₹"
                        aria-label={copy.receipt.costLabel(l.product_name)}
                        value={row.cost}
                        onChange={(ev) => setRow(l.id, { cost: ev.target.value })}
                      />
                    )}
                  </Field>
                  {tracked(index) ? (
                    <>
                      <Field label={copy.receipt.columns.batch} error={e.batchNo}>
                        {(ids) => (
                          <Input
                            {...ids}
                            aria-label={copy.receipt.batchLabel(l.product_name)}
                            value={row.batchNo}
                            onChange={(ev) => setRow(l.id, { batchNo: ev.target.value })}
                          />
                        )}
                      </Field>
                      <Field
                        label={copy.receipt.columns.expiry}
                        error={e.expiry}
                        hint={copy.receipt.expiryHint}
                      >
                        {(ids) => (
                          <DatePicker
                            {...ids}
                            value={row.expiry}
                            onChange={(iso) => setRow(l.id, { expiry: iso })}
                            min={addDays(receivedOn || todayIso(), 1)}
                          />
                        )}
                      </Field>
                      <Field label={copy.receipt.columns.mrp} error={e.mrp}>
                        {(ids) => (
                          <NumberInput
                            {...ids}
                            suffix="₹"
                            aria-label={copy.receipt.mrpLabel(l.product_name)}
                            value={row.mrp}
                            onChange={(ev) => setRow(l.id, { mrp: ev.target.value })}
                          />
                        )}
                      </Field>
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>

        {overReceived ? (
          <div className="space-y-3 rounded-md bg-medium-soft p-3">
            <p className="text-base">{copy.receipt.exceptionHint(quantity(openTotal))}</p>
            <Checkbox
              checked={exception}
              onCheckedChange={setException}
              label={copy.receipt.exception}
            />
            {exception ? (
              <TextareaField
                label={copy.receipt.exceptionNote}
                value={note}
                error={topErrors.note}
                onChange={(e) => setNote(e.target.value)}
              />
            ) : null}
          </div>
        ) : null}
        {formError ? <Banner tone="error">{formError}</Banner> : null}
      </div>
    </Dialog>
  );
}
