import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { post } from "@/lib/api";
import { errorText, isDecimal, toNumber } from "@/lib/forms";
import { lineTotalPaise, paiseToString } from "@/lib/decimal";
import { newKey } from "@/lib/hooks";
import { useApiQuery, useSuppliers } from "@/lib/queries";
import { money, quantity } from "@/lib/format";
import { purchases as copy } from "@/copy/purchases";
import type { Product, PurchaseOrder, Supplier, SupplierTerm } from "@/types/models";
import { ProductPicker } from "@/components/product-search";
import { Button } from "@/components/ui/button";
import { Banner, EmptyState, Mono, PageHeader, Panel } from "@/components/ui/display";
import { Field, NumberInput, SelectField, TextareaField } from "@/components/ui/field";
import { PackStepper, DateField, notify } from "@/components/ui/pickers";

type Line = {
  key: string;
  product: Product;
  quantity: string;
  cost: string;
  hasTerm: boolean;
  pack: number;
  moq: string;
};

function supplierFacts(supplier: Supplier): string | null {
  const days = (supplier.delivery_weekdays ?? [])
    .map((d) => copy.newPage.weekdays[d - 1])
    .filter(Boolean);
  const min = supplier.min_order_value ? money(supplier.min_order_value) : null;
  if (days.length && min) return copy.newPage.supplierFacts(days.join(", "), min);
  if (days.length) return copy.newPage.supplierDays(days.join(", "));
  if (min) return copy.newPage.supplierMin(min);
  return null;
}

export default function PurchaseNewPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [idemKey] = useState(() => newKey());
  const suppliers = useSuppliers();
  const [supplierId, setSupplierId] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [expected, setExpected] = useState("");
  const [notes, setNotes] = useState("");
  const [picked, setPicked] = useState<Product | null>(null);
  const [errors, setErrors] = useState<{
    supplier?: string;
    lines?: string;
    rows: Record<string, { quantity?: string; cost?: string }>;
  }>({ rows: {} });
  const [formError, setFormError] = useState<string | null>(null);

  const supplier = suppliers.data?.items.find((s) => s.id === supplierId);
  const terms = useApiQuery<SupplierTerm[]>(
    `/suppliers/${supplierId}/terms`,
    { current: true },
    { enabled: Boolean(supplierId) },
  );

  const addProduct = (product: Product) => {
    if (lines.some((l) => l.product.id === product.id)) return;
    const term = terms.data?.find((t) => t.product_id === product.id && t.in_force);
    const pack = term ? Number(term.pack_size) : 1;
    const moq = term ? Number(term.moq_units) : 0;
    setLines((current) => [
      ...current,
      {
        key: product.id,
        product,
        quantity: String(Math.max(pack, moq) || 1),
        cost: term ? String(Number(term.purchase_price)) : "",
        hasTerm: Boolean(term),
        pack,
        moq: term?.moq_units ?? "0",
      },
    ]);
    setPicked(null);
  };

  const update = (key: string, patch: Partial<Line>) =>
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  const total = paiseToString(
    lines.reduce(
      (sum, l) => sum + (lineTotalPaise(l.quantity || "0", l.cost || "0", "") ?? 0n),
      0n,
    ),
  );

  const create = useMutation({
    mutationFn: async (send: boolean) => {
      const order = await post<PurchaseOrder>(
        "/purchase-orders",
        {
          supplier_id: supplierId,
          expected_date: expected || undefined,
          notes: notes.trim() || undefined,
          lines: lines.map((l) => ({
            product_id: l.product.id,
            quantity_ordered: l.quantity,
            unit_cost: l.cost || undefined,
          })),
        },
        { idempotencyKey: `${idemKey}-${send ? "s" : "d"}` },
      );
      if (send) await post(`/purchase-orders/${order.id}/send`);
      return { order, send };
    },
    onSuccess: ({ order, send }) => {
      notify.success(send ? copy.newPage.createdSent : copy.newPage.created);
      void queryClient.invalidateQueries();
      navigate(`/purchases/${order.id}`);
    },
    onError: (error) => setFormError(errorText(error)),
  });

  const submit = (send: boolean) => {
    setFormError(null);
    const next: typeof errors = { rows: {} };
    if (!supplierId) next.supplier = copy.newPage.errors.supplier;
    if (lines.length === 0) next.lines = copy.newPage.errors.lines;
    for (const l of lines) {
      const row: { quantity?: string; cost?: string } = {};
      if (!isDecimal(l.quantity, 3) || toNumber(l.quantity) <= 0)
        row.quantity = copy.newPage.errors.quantity;
      if (l.cost !== "" ? !isDecimal(l.cost, 4) : !l.hasTerm) row.cost = copy.newPage.errors.cost;
      if (row.quantity || row.cost) next.rows[l.key] = row;
    }
    setErrors(next);
    if (next.supplier || next.lines || Object.keys(next.rows).length > 0) return;
    create.mutate(send);
  };

  return (
    <>
      <PageHeader
        title={copy.newPage.title}
        actions={
          <>
            <Button
              loading={create.isPending && create.variables === false}
              disabled={create.isPending}
              onClick={() => submit(false)}
            >
              {copy.newPage.saveDraft}
            </Button>
            <Button
              variant="primary"
              loading={create.isPending && create.variables === true}
              disabled={create.isPending}
              onClick={() => submit(true)}
            >
              {copy.newPage.saveSend}
            </Button>
          </>
        }
      />
      <div className="max-w-4xl space-y-6">
        {formError ? <Banner tone="error">{formError}</Banner> : null}
        <Panel>
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label={copy.newPage.supplier}
              error={errors.supplier}
              hint={supplier ? (supplierFacts(supplier) ?? undefined) : undefined}
              value={supplierId}
              onChange={(e) => {
                setSupplierId(e.target.value);
                setLines([]);
              }}
            >
              <option value="">{copy.newPage.pickSupplier}</option>
              {(suppliers.data?.items ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </SelectField>
            <DateField
              label={copy.newPage.expected}
              optional
              hint={copy.newPage.expectedHint}
              value={expected}
              onChange={setExpected}
            />
          </div>
        </Panel>

        <Panel title={copy.newPage.lines}>
          <div className="space-y-4">
            <div className="max-w-md">
              <Field label={copy.newPage.addProduct} error={errors.lines}>
                {(ids) => (
                  <ProductPicker
                    {...ids}
                    value={picked}
                    disabled={!supplierId}
                    placeholder={copy.newPage.pickProduct}
                    onChange={addProduct}
                  />
                )}
              </Field>
            </div>
            {lines.length === 0 ? (
              <EmptyState
                title={copy.newPage.emptyLines}
                hint={copy.newPage.emptyLinesHint}
                className="px-0"
              />
            ) : (
              <div className="relative overflow-x-auto rounded-md border border-border">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">{copy.newPage.lines}</caption>
                  <thead className="bg-surface-2 text-xs text-text-2">
                    <tr>
                      <th scope="col" className="h-9 px-3 text-left font-medium">
                        {copy.newPage.columns.product}
                      </th>
                      <th scope="col" className="h-9 px-3 text-left font-medium">
                        {copy.newPage.columns.quantity}
                      </th>
                      <th scope="col" className="h-9 w-32 px-3 text-right font-medium">
                        {copy.newPage.columns.cost} (₹)
                      </th>
                      <th scope="col" className="h-9 w-28 px-3 text-right font-medium">
                        {copy.newPage.columns.value} (₹)
                      </th>
                      <th scope="col" className="h-9 w-10 px-1">
                        <span className="sr-only">{copy.newPage.columns.remove}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => {
                      const row = errors.rows[l.key] ?? {};
                      const paise = lineTotalPaise(l.quantity || "0", l.cost || "0", "");
                      return (
                        <tr key={l.key} className="border-t border-border align-top">
                          <td className="px-3 py-2">
                            <div className="font-medium">{l.product.name}</div>
                            <Mono className="text-text-3">{l.product.sku}</Mono>
                            <div className="text-xs text-text-3">
                              {copy.newPage.packOf(quantity(l.pack))}
                              {Number(l.moq) > 0
                                ? `. ${copy.newPage.minimum(quantity(l.moq))}`
                                : ""}
                            </div>
                            {!l.hasTerm ? (
                              <div className="text-xs text-high">{copy.newPage.noTerms}</div>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">
                            <PackStepper
                              value={Number(l.quantity) || 0}
                              packSize={l.pack}
                              ariaLabel={copy.newPage.quantityLabel(l.product.name)}
                              onChange={(units) => update(l.key, { quantity: String(units) })}
                            />
                            {row.quantity ? (
                              <div className="mt-1 text-xs text-critical">{row.quantity}</div>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">
                            <NumberInput
                              aria-label={copy.newPage.costLabel(l.product.name)}
                              aria-invalid={row.cost ? true : undefined}
                              value={l.cost}
                              onChange={(e) => update(l.key, { cost: e.target.value })}
                              className="h-8"
                            />
                            {row.cost ? (
                              <div className="mt-1 text-xs text-critical">{row.cost}</div>
                            ) : null}
                          </td>
                          <td className="tabular px-3 py-2 pt-3 text-right">
                            {paise === null ? "" : money(paiseToString(paise), 2).replace("₹", "")}
                          </td>
                          <td className="px-1 py-1.5">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="px-2"
                              aria-label={copy.newPage.removeLine(l.product.name)}
                              onClick={() =>
                                setLines((current) => current.filter((x) => x.key !== l.key))
                              }
                            >
                              <X size={14} strokeWidth={1.5} />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {lines.length > 0 ? (
              <p className="text-right text-base">
                {copy.newPage.total}:{" "}
                <span className="tabular font-semibold">{money(total, 2)}</span>
              </p>
            ) : null}
          </div>
        </Panel>

        <Panel>
          <TextareaField
            label={copy.newPage.notes}
            optional
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </Panel>
      </div>
    </>
  );
}
