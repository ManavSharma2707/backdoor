import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Controller, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { patch, post } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { applyServerErrors, isDecimal, toNumber } from "@/lib/forms";
import { useApiQuery, useCategories, useSuppliers } from "@/lib/queries";
import { common } from "@/copy/common";
import { products as copy } from "@/copy/products";
import type { Product, ProductCreate, ProductPatch, TaxRate } from "@/types/models";
import { Button } from "@/components/ui/button";
import { Banner, PageHeader, Panel, Skeleton } from "@/components/ui/display";
import { Switch } from "@/components/ui/controls";
import { NumberField, SelectField, TextareaField, TextField } from "@/components/ui/field";
import { DateField, notify } from "@/components/ui/pickers";

const UNITS = [
  "pcs",
  "pack",
  "strip",
  "bottle",
  "tube",
  "sachet",
  "box",
  "kg",
  "litre",
  "vial",
  "tin",
] as const;
const money = z
  .string()
  .trim()
  .refine((v) => isDecimal(v, 2), copy.form.errors.price);
const qty = z
  .string()
  .trim()
  .refine((v) => isDecimal(v, 3), copy.form.errors.quantity);
const optionalDays = z
  .string()
  .trim()
  .refine((v) => v === "" || /^\d+$/.test(v), copy.form.errors.days);

const schema = z
  .object({
    name: z.string().trim().min(1, copy.form.errors.name),
    sku: z.string().trim().min(1, copy.form.errors.sku),
    brand: z.string().trim(),
    category_id: z.string().min(1, copy.form.errors.category),
    base_unit: z.enum(UNITS),
    pack_label: z.string().trim(),
    barcode: z.string().trim(),
    mrp: money,
    selling_price: money,
    tax_rate_id: z.string().min(1, copy.form.errors.taxRate),
    price_change_reason: z.string().trim(),
    is_batch_tracked: z.boolean(),
    shelf_life_days: optionalDays,
    min_stock_qty: qty,
    is_seasonal: z.boolean(),
    launched_on: z.string(),
    generic_name: z.string().trim(),
    strength: z.string().trim(),
    dosage_form: z.string().trim(),
    manufacturer: z.string().trim(),
    schedule_class: z.enum(["", "H", "H1", "X"]),
    supplier_id: z.string(),
    purchase_price: z.string().trim(),
    pack_size: z.string().trim(),
    moq_units: z.string().trim(),
    lead_time_days: optionalDays,
    notes: z.string().trim(),
  })
  .superRefine((v, ctx) => {
    if (
      isDecimal(v.mrp, 2) &&
      isDecimal(v.selling_price, 2) &&
      toNumber(v.selling_price) > toNumber(v.mrp)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["selling_price"],
        message: copy.form.errors.priceOver,
      });
    }
    if (v.supplier_id) {
      if (!isDecimal(v.purchase_price, 4)) {
        ctx.addIssue({
          code: "custom",
          path: ["purchase_price"],
          message: copy.form.errors.supplierCost,
        });
      }
      if (!isDecimal(v.pack_size, 3) || toNumber(v.pack_size) <= 0) {
        ctx.addIssue({
          code: "custom",
          path: ["pack_size"],
          message: copy.form.errors.supplierPack,
        });
      }
      if (v.moq_units !== "" && !isDecimal(v.moq_units, 3)) {
        ctx.addIssue({ code: "custom", path: ["moq_units"], message: copy.form.errors.quantity });
      }
    }
  });

type Values = z.infer<typeof schema>;

const EMPTY: Values = {
  name: "",
  sku: "",
  brand: "",
  category_id: "",
  base_unit: "pack",
  pack_label: "",
  barcode: "",
  mrp: "",
  selling_price: "",
  tax_rate_id: "",
  price_change_reason: "",
  is_batch_tracked: false,
  shelf_life_days: "",
  min_stock_qty: "0",
  is_seasonal: false,
  launched_on: "",
  generic_name: "",
  strength: "",
  dosage_form: "",
  manufacturer: "",
  schedule_class: "",
  supplier_id: "",
  purchase_price: "",
  pack_size: "1",
  moq_units: "",
  lead_time_days: "",
  notes: "",
};

const SERVER_FIELDS = Object.keys(EMPTY);

function fromProduct(p: Product): Values {
  return {
    ...EMPTY,
    name: p.name,
    sku: p.sku,
    brand: p.brand ?? "",
    category_id: p.category_id,
    base_unit: p.base_unit as Values["base_unit"],
    pack_label: p.pack_label ?? "",
    barcode: p.barcode ?? "",
    mrp: p.mrp,
    selling_price: p.selling_price,
    tax_rate_id: p.tax_rate_id,
    is_batch_tracked: p.is_batch_tracked,
    shelf_life_days: p.shelf_life_days ? String(p.shelf_life_days) : "",
    min_stock_qty: String(Number(p.min_stock_qty)),
    is_seasonal: p.is_seasonal,
    launched_on: p.launched_on ?? "",
    generic_name: p.generic_name ?? "",
    strength: p.strength ?? "",
    dosage_form: p.dosage_form ?? "",
    manufacturer: p.manufacturer ?? "",
    schedule_class: (p.schedule_class as Values["schedule_class"]) ?? "",
    notes: p.notes ?? "",
  };
}

const orNull = (value: string) => (value === "" ? null : value);

export default function ProductFormPage() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { tenant } = useSession();
  const medical = tenant.business_type === "medical";
  const [formError, setFormError] = useState<string | null>(null);

  const categories = useCategories();
  const suppliers = useSuppliers();
  const taxRates = useApiQuery<TaxRate[]>("/tax-rates", undefined, { staleTime: 10 * 60_000 });
  const existing = useApiQuery<Product>(`/products/${id}`, undefined, { enabled: editing });

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError,
    formState: { errors, dirtyFields },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY, mode: "onBlur" });

  useEffect(() => {
    if (existing.data) reset(fromProduct(existing.data));
  }, [existing.data, reset]);

  const supplierId = useWatch({ control, name: "supplier_id" });
  const priceChanged = Boolean(dirtyFields.selling_price || dirtyFields.mrp);

  const save = useMutation({
    mutationFn: async (values: Values) => {
      const base = {
        name: values.name,
        sku: values.sku,
        brand: orNull(values.brand),
        category_id: values.category_id,
        base_unit: values.base_unit,
        pack_label: orNull(values.pack_label),
        barcode: orNull(values.barcode),
        mrp: values.mrp,
        selling_price: values.selling_price,
        tax_rate_id: values.tax_rate_id,
        is_batch_tracked: values.is_batch_tracked,
        shelf_life_days: values.shelf_life_days === "" ? null : Number(values.shelf_life_days),
        min_stock_qty: values.min_stock_qty,
        is_seasonal: values.is_seasonal,
        launched_on: orNull(values.launched_on),
        notes: orNull(values.notes),
        ...(medical
          ? {
              generic_name: orNull(values.generic_name),
              strength: orNull(values.strength),
              dosage_form: orNull(values.dosage_form),
              manufacturer: orNull(values.manufacturer),
              schedule_class: values.schedule_class === "" ? null : values.schedule_class,
            }
          : {}),
      };
      if (editing) {
        const body: ProductPatch = {
          ...base,
          price_change_reason: priceChanged ? orNull(values.price_change_reason) : undefined,
        };
        return patch<Product>(`/products/${id}`, body);
      }
      const created = await post<Product>("/products", base as ProductCreate);
      if (values.supplier_id) {
        await post(`/suppliers/${values.supplier_id}/terms`, {
          product_id: created.id,
          purchase_price: values.purchase_price,
          pack_size: values.pack_size,
          moq_units: values.moq_units || "0",
          lead_time_days: values.lead_time_days === "" ? null : Number(values.lead_time_days),
          is_primary: true,
        });
      }
      return created;
    },
    onSuccess: (product) => {
      notify.success(editing ? copy.form.saved : copy.form.created);
      void queryClient.invalidateQueries();
      navigate(`/products/${product.id}`);
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await save.mutateAsync(values);
    } catch (error) {
      setFormError(applyServerErrors(error, setError, SERVER_FIELDS));
    }
  });

  if (editing && existing.isLoading) return <Skeleton className="h-96 w-full" />;
  if (editing && existing.isError) return <Banner tone="error">{copy.detail.notFound}</Banner>;

  const title = editing ? copy.form.editTitle(existing.data?.name ?? "") : copy.form.addTitle;

  return (
    <form onSubmit={onSubmit} noValidate>
      <PageHeader
        title={title}
        actions={
          <>
            <Button onClick={() => navigate(-1)}>{copy.form.cancel}</Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              {editing ? copy.form.save : copy.form.create}
            </Button>
          </>
        }
      />
      <div className="max-w-3xl space-y-6">
        {formError ? <Banner tone="error">{formError}</Banner> : null}

        <Panel title={copy.form.sections.basic}>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label={copy.form.name}
              error={errors.name?.message}
              wrapperClassName="sm:col-span-2"
              {...register("name")}
            />
            <TextField label={copy.form.sku} error={errors.sku?.message} {...register("sku")} />
            <TextField
              label={copy.form.brand}
              optional
              error={errors.brand?.message}
              {...register("brand")}
            />
            <SelectField
              label={copy.form.category}
              error={errors.category_id?.message}
              {...register("category_id")}
            >
              <option value="">{copy.form.pickCategory}</option>
              {(categories.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </SelectField>
            <SelectField label={copy.form.baseUnit} {...register("base_unit")}>
              {UNITS.map((u) => (
                <option key={u} value={u}>
                  {copy.unitName(u)}
                </option>
              ))}
            </SelectField>
            <TextField
              label={copy.form.packLabel}
              optional
              hint={copy.form.packLabelHint}
              {...register("pack_label")}
            />
            <TextField
              label={copy.form.barcode}
              optional
              error={errors.barcode?.message}
              {...register("barcode")}
            />
          </div>
        </Panel>

        <Panel title={copy.form.sections.price}>
          <div className="grid gap-4 sm:grid-cols-3">
            <NumberField
              label={copy.form.mrp}
              suffix="₹"
              error={errors.mrp?.message}
              {...register("mrp")}
            />
            <NumberField
              label={copy.form.sellingPrice}
              suffix="₹"
              error={errors.selling_price?.message}
              {...register("selling_price")}
            />
            <SelectField
              label={copy.form.taxRate}
              error={errors.tax_rate_id?.message}
              {...register("tax_rate_id")}
            >
              <option value="">{copy.form.pickTaxRate}</option>
              {(taxRates.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </SelectField>
          </div>
          <p className="mt-2 text-xs text-text-3">{copy.form.sellingPriceHint}</p>
          {editing && priceChanged ? (
            <div className="mt-4 max-w-md">
              <TextField
                label={copy.form.priceChangeReason}
                optional
                {...register("price_change_reason")}
              />
            </div>
          ) : null}
        </Panel>

        <Panel title={copy.form.sections.stock}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Controller
                control={control}
                name="is_batch_tracked"
                render={({ field }) => (
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    label={copy.form.batchTracked}
                    hint={copy.form.batchTrackedHint}
                  />
                )}
              />
            </div>
            <NumberField
              label={copy.form.shelfLife}
              optional
              suffix={common.units.days}
              decimals={false}
              error={errors.shelf_life_days?.message}
              {...register("shelf_life_days")}
            />
            <NumberField
              label={copy.form.minStock}
              error={errors.min_stock_qty?.message}
              {...register("min_stock_qty")}
            />
            <Controller
              control={control}
              name="launched_on"
              render={({ field }) => (
                <DateField
                  label={copy.form.launchedOn}
                  optional
                  value={field.value}
                  onChange={field.onChange}
                />
              )}
            />
            <div className="self-end">
              <Controller
                control={control}
                name="is_seasonal"
                render={({ field }) => (
                  <Switch
                    checked={field.value}
                    onCheckedChange={field.onChange}
                    label={copy.form.seasonal}
                  />
                )}
              />
            </div>
          </div>
        </Panel>

        {medical ? (
          <Panel title={copy.form.sections.medicine}>
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField label={copy.form.genericName} optional {...register("generic_name")} />
              <TextField label={copy.form.strength} optional {...register("strength")} />
              <TextField label={copy.form.dosageForm} optional {...register("dosage_form")} />
              <TextField label={copy.form.manufacturer} optional {...register("manufacturer")} />
              <SelectField label={copy.form.schedule} {...register("schedule_class")}>
                <option value="">{copy.form.scheduleNone}</option>
                <option value="H">H</option>
                <option value="H1">H1</option>
                <option value="X">X</option>
              </SelectField>
            </div>
          </Panel>
        ) : null}

        {!editing ? (
          <Panel title={copy.form.sections.supplier}>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label={copy.form.supplier}
                hint={copy.form.supplierSkipHint}
                {...register("supplier_id")}
              >
                <option value="">{copy.form.pickSupplier}</option>
                {(suppliers.data?.items ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </SelectField>
              {supplierId ? (
                <>
                  <NumberField
                    label={copy.form.purchasePrice}
                    suffix="₹"
                    error={errors.purchase_price?.message}
                    {...register("purchase_price")}
                  />
                  <NumberField
                    label={copy.form.packOf}
                    error={errors.pack_size?.message}
                    {...register("pack_size")}
                  />
                  <NumberField
                    label={copy.form.minimumOrder}
                    optional
                    error={errors.moq_units?.message}
                    {...register("moq_units")}
                  />
                  <NumberField
                    label={copy.form.deliveryTime}
                    optional
                    suffix={common.units.days}
                    decimals={false}
                    hint={copy.form.deliveryTimeHint}
                    error={errors.lead_time_days?.message}
                    {...register("lead_time_days")}
                  />
                </>
              ) : null}
            </div>
          </Panel>
        ) : null}

        <Panel title={copy.form.sections.notes}>
          <TextareaField label={copy.form.notes} optional {...register("notes")} />
        </Panel>
      </div>
    </form>
  );
}
