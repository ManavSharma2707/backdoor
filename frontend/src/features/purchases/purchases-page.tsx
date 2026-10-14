import { useCallback } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryParams } from "@/lib/hooks";
import { useListQuery, useSuppliers } from "@/lib/queries";
import { formatDate, money, quantity } from "@/lib/format";
import { purchases as copy } from "@/copy/purchases";
import type { PurchaseListItem } from "@/types/models";
import { SearchBox } from "@/components/search-box";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/controls";
import { EmptyState, PageHeader, StatusChip, type Tone } from "@/components/ui/display";
import { Select } from "@/components/ui/field";
import { DataTable, Pagination, type Column } from "@/components/ui/table";

export const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  sent: "info",
  partially_received: "medium",
  received: "ok",
  cancelled: "neutral",
  closed: "neutral",
};

export default function PurchasesPage() {
  const navigate = useNavigate();
  const [params, setParams] = useQueryParams({
    status: "",
    supplier_id: "",
    overdue: "",
    q: "",
    page: "1",
    page_size: "50",
  });
  const suppliers = useSuppliers();
  const list = useListQuery<PurchaseListItem>("/purchase-orders", { ...params });
  const setQ = useCallback((q: string) => setParams({ q }), [setParams]);

  const columns: Column<PurchaseListItem>[] = [
    {
      key: "order",
      header: copy.columns.order,
      cell: (o) => (
        <Link to={`/purchases/${o.id}`} className="font-mono text-sm font-medium hover:underline">
          {o.po_number}
        </Link>
      ),
    },
    {
      key: "supplier",
      header: copy.columns.supplier,
      className: "min-w-48",
      cell: (o) => o.supplier_name,
    },
    { key: "date", header: copy.columns.date, cell: (o) => formatDate(o.order_date) },
    {
      key: "expected",
      header: copy.columns.expected,
      cell: (o) => (
        <span>
          {formatDate(o.expected_date)}
          {o.is_overdue ? (
            <span className="block text-xs text-high">{copy.daysLate(o.days_late)}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "status",
      header: copy.columns.status,
      cell: (o) => (
        <StatusChip tone={STATUS_TONE[o.status] ?? "neutral"}>
          {copy.status[o.status as keyof typeof copy.status]}
        </StatusChip>
      ),
    },
    { key: "lines", header: copy.columns.lines, numeric: true, cell: (o) => quantity(o.lines) },
    {
      key: "value",
      header: copy.columns.value,
      unit: "₹",
      numeric: true,
      cell: (o) => money(o.value, 2).replace("₹", ""),
    },
    {
      key: "received",
      header: copy.columns.received,
      unit: "₹",
      numeric: true,
      cell: (o) =>
        Number(o.received_value) > 0 ? money(o.received_value, 2).replace("₹", "") : "0",
    },
  ];

  return (
    <>
      <PageHeader
        title={copy.title}
        context={list.data ? String(list.data.total) : undefined}
        actions={
          <Link to="/purchases/new">
            <Button variant="primary">{copy.newOrder}</Button>
          </Link>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchBox
          value={params.q}
          onChange={setQ}
          label={copy.filters.search}
          placeholder={copy.filters.searchPlaceholder}
        />
        <div className="w-full sm:w-44">
          <Select
            aria-label={copy.filters.status}
            value={params.status}
            onChange={(e) => setParams({ status: e.target.value })}
          >
            <option value="">{copy.filters.allStatuses}</option>
            {Object.entries(copy.status).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="w-full sm:w-56">
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
        <div className="pb-2">
          <Checkbox
            checked={params.overdue === "true"}
            onCheckedChange={(on) => setParams({ overdue: on ? "true" : "" })}
            label={copy.filters.overdueOnly}
          />
        </div>
      </div>
      <DataTable
        caption={copy.title}
        columns={columns}
        rows={list.data?.items}
        rowId={(o) => o.id}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        onRowClick={(o) => navigate(`/purchases/${o.id}`)}
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
