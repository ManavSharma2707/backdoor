import { useCallback } from "react";
import { Link, useNavigate } from "react-router";
import { useListQuery, useCategories, useSuppliers } from "@/lib/queries";
import { useQueryParams } from "@/lib/hooks";
import { money, quantity } from "@/lib/format";
import { products as copy } from "@/copy/products";
import type { Product } from "@/types/models";
import { SearchBox } from "@/components/search-box";
import { Button } from "@/components/ui/button";
import { EmptyState, Mono, PageHeader, StatusChip, type Tone } from "@/components/ui/display";
import { Select } from "@/components/ui/field";
import { DataTable, Pagination, type Column } from "@/components/ui/table";

const DEFAULTS = {
  q: "",
  category_id: "",
  supplier_id: "",
  status: "active",
  batch_tracked: "",
  page: "1",
  page_size: "50",
};

const PLAN_TONE: Record<string, Tone> = {
  buy: "critical",
  watch: "high",
  ok: "ok",
  not_selling: "neutral",
};

export default function ProductsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useQueryParams(DEFAULTS);
  const categories = useCategories();
  const suppliers = useSuppliers();
  const list = useListQuery<Product>("/products", {
    q: params.q,
    category_id: params.category_id,
    supplier_id: params.supplier_id,
    status: params.status,
    batch_tracked: params.batch_tracked,
    page: params.page,
    page_size: params.page_size,
  });
  const setQuery = useCallback((q: string) => setParams({ q }), [setParams]);
  const rows = list.data?.items;
  const showCover = rows?.some((p) => p.days_of_cover !== null) ?? false;
  const showPlan = rows?.some((p) => p.plan_status !== null) ?? false;

  const columns: Column<Product>[] = [
    {
      key: "product",
      header: copy.columns.product,
      className: "min-w-56",
      cell: (p) => (
        <div className="py-1">
          <Link to={`/products/${p.id}`} className="font-medium hover:underline">
            {p.name}
          </Link>
          <div className="flex items-center gap-2">
            <Mono className="text-text-3">{p.sku}</Mono>
            {!p.is_active ? <StatusChip>{copy.inactive}</StatusChip> : null}
          </div>
        </div>
      ),
    },
    { key: "category", header: copy.columns.category, cell: (p) => p.category_name },
    {
      key: "unit",
      header: copy.columns.unit,
      cell: (p) => [copy.unitName(p.base_unit), p.pack_label].filter(Boolean).join(", "),
    },
    {
      key: "price",
      header: copy.columns.price,
      unit: "₹",
      numeric: true,
      cell: (p) => money(p.selling_price, 2).replace("₹", ""),
    },
    { key: "stock", header: copy.columns.stock, numeric: true, cell: (p) => quantity(p.on_hand) },
    ...(showCover
      ? [
          {
            key: "cover",
            header: copy.columns.cover,
            numeric: true,
            cell: (p: Product) => (p.days_of_cover === null ? "" : quantity(p.days_of_cover)),
          } satisfies Column<Product>,
        ]
      : []),
    ...(showPlan
      ? [
          {
            key: "plan",
            header: copy.columns.plan,
            cell: (p: Product) =>
              p.plan_status ? (
                <StatusChip tone={PLAN_TONE[p.plan_status] ?? "neutral"}>
                  {copy.planStatus[p.plan_status as keyof typeof copy.planStatus] ??
                    copy.planStatus.unknown}
                </StatusChip>
              ) : null,
          } satisfies Column<Product>,
        ]
      : []),
    { key: "supplier", header: copy.columns.supplier, cell: (p) => p.primary_supplier_name ?? "" },
  ];

  return (
    <>
      <PageHeader
        title={copy.title}
        context={list.data ? copy.count(list.data.total) : undefined}
        actions={
          <Link to="/products/new">
            <Button variant="primary">{copy.addProduct}</Button>
          </Link>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchBox
          value={params.q}
          onChange={setQuery}
          label={copy.searchLabel}
          placeholder={copy.searchPlaceholder}
        />
        <div className="w-full sm:w-52">
          <Select
            aria-label={copy.filters.category}
            value={params.category_id}
            onChange={(e) => setParams({ category_id: e.target.value })}
          >
            <option value="">{copy.filters.allCategories}</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-52">
          <Select
            aria-label={copy.filters.supplier}
            value={params.supplier_id}
            onChange={(e) => setParams({ supplier_id: e.target.value })}
          >
            <option value="">{copy.filters.allSuppliers}</option>
            {(suppliers.data?.items ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-36">
          <Select
            aria-label={copy.filters.status}
            value={params.status}
            onChange={(e) => setParams({ status: e.target.value })}
          >
            <option value="active">{copy.filters.statusActive}</option>
            <option value="inactive">{copy.filters.statusInactive}</option>
            <option value="all">{copy.filters.statusAll}</option>
          </Select>
        </div>
        <div className="w-full sm:w-44">
          <Select
            aria-label={copy.filters.batchTracked}
            value={params.batch_tracked}
            onChange={(e) => setParams({ batch_tracked: e.target.value })}
          >
            <option value="">{copy.filters.batchAll}</option>
            <option value="true">{copy.filters.batchYes}</option>
            <option value="false">{copy.filters.batchNo}</option>
          </Select>
        </div>
      </div>
      <DataTable
        caption={copy.title}
        columns={columns}
        rows={rows}
        rowId={(p) => p.id}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        onRowClick={(p) => navigate(`/products/${p.id}`)}
        empty={<EmptyState title={copy.empty} hint={copy.emptyHint} />}
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
