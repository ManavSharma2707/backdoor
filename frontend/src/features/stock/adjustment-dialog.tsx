import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { post } from "@/lib/api";
import { applyServerErrors } from "@/lib/forms";
import { newKey } from "@/lib/hooks";
import { useApiQuery } from "@/lib/queries";
import { formatDate, quantity } from "@/lib/format";
import { common } from "@/copy/common";
import { stock as copy } from "@/copy/stock";
import type { AdjustmentCreate, Product, ProductStock } from "@/types/models";
import { ProductPicker } from "@/components/product-search";
import { Button } from "@/components/ui/button";
import { Banner } from "@/components/ui/display";
import { Field, NumberField, SelectField, TextareaField } from "@/components/ui/field";
import { Dialog } from "@/components/ui/overlay";
import { notify } from "@/components/ui/pickers";

const REASONS = [
  "damage",
  "expiry_writeoff",
  "theft_loss",
  "found",
  "correction",
  "supplier_return",
  "other",
] as const;

const schema = z
  .object({
    product: z.object({ id: z.string() }).nullable(),
    batchId: z.string(),
    change: z
      .string()
      .trim()
      .regex(/^[+-]?\d+(\.\d{1,3})?$/, copy.adjust.errors.change),
    reason: z.enum(REASONS),
    note: z.string().trim(),
  })
  .superRefine((value, ctx) => {
    if (!value.product)
      ctx.addIssue({ code: "custom", path: ["product"], message: copy.adjust.errors.product });
    if (Number(value.change) === 0 && /^[+-]?\d/.test(value.change)) {
      ctx.addIssue({ code: "custom", path: ["change"], message: copy.adjust.errors.zero });
    }
    if (value.reason === "other" && !value.note) {
      ctx.addIssue({ code: "custom", path: ["note"], message: copy.adjust.errors.note });
    }
  });

type Values = z.infer<typeof schema>;

export function AdjustmentDialog({
  open,
  onOpenChange,
  product: initial,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  product?: Product | null;
}) {
  const queryClient = useQueryClient();
  const keyRef = useRef(newKey());
  const [formError, setFormError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Product | null>(initial ?? null);

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError,
    setValue,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { product: null, batchId: "", change: "", reason: "correction", note: "" },
  });

  useEffect(() => {
    if (open) {
      keyRef.current = newKey();
      setFormError(null);
      setPicked(initial ?? null);
      reset({
        product: initial ? { id: initial.id } : null,
        batchId: "",
        change: "",
        reason: "correction",
        note: "",
      });
    }
  }, [open, initial, reset]);

  const productId = picked?.id;
  const stockInfo = useApiQuery<ProductStock>(`/products/${productId}/stock`, undefined, {
    enabled: Boolean(productId),
  });
  const tracked = Boolean(picked?.is_batch_tracked);
  const reason = useWatch({ control, name: "reason" });

  const save = useMutation({
    mutationFn: (body: AdjustmentCreate) =>
      post("/inventory/adjustments", body, { idempotencyKey: keyRef.current }),
    onSuccess: () => {
      notify.success(copy.adjust.saved);
      void queryClient.invalidateQueries();
      onOpenChange(false);
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    if (tracked && !values.batchId) {
      setError("batchId", { message: copy.adjust.errors.batch });
      return;
    }
    try {
      await save.mutateAsync({
        product_id: values.product?.id ?? "",
        batch_id: tracked ? values.batchId : undefined,
        quantity_delta: values.change.replace(/^\+/, ""),
        reason_code: values.reason,
        note: values.note || undefined,
      });
    } catch (error) {
      setFormError(
        applyServerErrors(error, setError, ["quantity_delta", "batch_id", "note", "product_id"]),
      );
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.adjust.title}
      wide
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => void onSubmit()}>
            {copy.adjust.save}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <Controller
          control={control}
          name="product"
          render={() => (
            <Field label={copy.adjust.product} error={errors.product?.message}>
              {(ids) => (
                <ProductPicker
                  {...ids}
                  value={picked}
                  placeholder={copy.adjust.pickProduct}
                  onChange={(next) => {
                    setPicked(next);
                    setValue("product", { id: next.id }, { shouldValidate: true });
                    setValue("batchId", "");
                  }}
                />
              )}
            </Field>
          )}
        />
        {picked && stockInfo.data ? (
          <p className="text-sm text-text-2">
            {copy.adjust.onHandNow(quantity(stockInfo.data.on_hand))}
          </p>
        ) : null}
        {tracked ? (
          <SelectField
            label={copy.adjust.batch}
            error={errors.batchId?.message}
            {...register("batchId")}
          >
            <option value="">{copy.adjust.pickBatch}</option>
            {(stockInfo.data?.batches ?? []).map((batch) => (
              <option key={batch.batch_id} value={batch.batch_id}>
                {batch.batch_no}, {formatDate(batch.expiry_date)}, {quantity(batch.on_hand)}
              </option>
            ))}
          </SelectField>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField
            label={copy.adjust.change}
            hint={copy.adjust.changeHint}
            error={errors.change?.message}
            {...register("change")}
          />
          <SelectField label={copy.adjust.reason} {...register("reason")}>
            {REASONS.map((code) => (
              <option key={code} value={code}>
                {copy.adjust.reasons[code]}
              </option>
            ))}
          </SelectField>
        </div>
        <TextareaField
          label={copy.adjust.note}
          optional={reason !== "other"}
          error={errors.note?.message}
          {...register("note")}
        />
        {formError ? <Banner tone="error">{formError}</Banner> : null}
      </form>
    </Dialog>
  );
}
