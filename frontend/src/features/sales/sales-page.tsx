import { useCallback, useMemo } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryParams } from "@/lib/hooks";
import { useApiQuery, useListQuery } from "@/lib/queries";
import { addDays, dateRange, formatDateTime, money, quantity, todayIso } from "@/lib/format";
import { sales as copy } from "@/copy/sales";
import type { SaleListItem, SalesSummary } from "@/types/models";
import { SearchBox } from "@/components/search-box";
import { Button } from "@/components/ui/button";
import { EmptyState, PageHeader, StatusChip } from "@/components/ui/display";
import { Select } from "@/components/ui/field";
import { DateField } from "@/components/ui/pickers";
import { DataTable, Pagination, type Column, type SortState } from "@/components/ui/table";

export default function SalesPage() {
  const navigate = useNavigate();
  const today = todayIso();
  const defaults = useMemo(
    () => ({
      from: addDays(today, -6),
      to: today,
      q: "",
      status: "",
      sort: "",
      page: "1",
      page_size: "50",
    }),
    [today],
  );
  const [params, setParams] = useQueryParams(defaults);
  const query = {
    from: params.from,
    to: params.to,
    q: params.q,
    status: params.status,
    sort: params.sort,
    page: params.page,
    page_size: params.page_size,
  };
  const list = useListQuery<SaleListItem>("/sales", query);
  const summary = useApiQuery<SalesSummary>("/sales/summary", { from: params.from, to: params.to });
  const setQ = useCallback((q: string) => setParams({ q }), [setParams]);

  const [sortField = "", sortDir = "asc"] = params.sort.split(":");
  const sort: SortState = sortField
    ? { field: sortField, dir: sortDir === "desc" ? "desc" : "asc" }
    : null;

  const columns: Column<SaleListItem>[] = [
    {
      key: "bill",
      header: copy.columns.bill,
      sortField: "bill_no",
      cell: (s) => (
        <Link to={`/sales/${s.id}`} className="font-mono text-sm font-medium hover:underline">
          {s.bill_no}
        </Link>
      ),
    },
    {
      key: "when",
      header: copy.columns.when,
      sortField: "sold_at",
      cell: (s) => formatDateTime(s.sold_at),
    },
    { key: "items", header: copy.columns.items, numeric: true, cell: (s) => quantity(s.items) },
    {
      key: "payment",
      header: copy.columns.payment,
      cell: (s) => copy.payment[s.payment_mode as keyof typeof copy.payment],
    },
    {
      key: "total",
      header: copy.columns.total,
      unit: "₹",
      numeric: true,
      sortField: "total",
      cell: (s) => (
        <span>
          {money(s.total, 2).replace("₹", "")}
          {Number(s.returned_total) > 0 ? (
            <span className="block text-xs text-text-3">
              {copy.returned(money(s.returned_total, 2))}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "status",
      header: copy.columns.status,
      cell: (s) => (
        <StatusChip tone={s.status === "void" ? "critical" : "ok"}>
          {copy.status[s.status as keyof typeof copy.status]}
        </StatusChip>
      ),
    },
  ];

  const s = summary.data;
  return (
    <>
      <PageHeader
        title={copy.title}
        context={dateRange(params.from, params.to)}
        actions={
          <Link to="/sales/new">
            <Button variant="primary">{copy.newBill}</Button>
          </Link>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <DateField
          label={copy.filters.from}
          value={params.from}
          onChange={(from) => from && setParams({ from })}
          className="w-44"
        />
        <DateField
          label={copy.filters.to}
          value={params.to}
          onChange={(to) => to && setParams({ to })}
          className="w-44"
        />
        <SearchBox
          value={params.q}
          onChange={setQ}
          label={copy.filters.search}
          placeholder={copy.filters.searchPlaceholder}
        />
        <div className="w-full sm:w-40">
          <Select
            aria-label={copy.filters.status}
            value={params.status}
            onChange={(e) => setParams({ status: e.target.value })}
          >
            <option value="">{copy.filters.allStatuses}</option>
            <option value="completed">{copy.filters.completed}</option>
            <option value="void">{copy.filters.void}</option>
          </Select>
        </div>
      </div>
      <dl className="mb-4 grid grid-cols-3 gap-6 rounded-md border border-border bg-surface px-4 py-3 sm:max-w-xl">
        {[
          { label: copy.summary.bills, value: s ? quantity(s.bills) : "" },
          { label: copy.summary.sales, value: s ? money(s.sales) : "" },
          { label: copy.summary.returns, value: s ? money(s.returns) : "" },
        ].map((item) => (
          <div key={item.label}>
            <dt className="text-xs text-text-2">{item.label}</dt>
            <dd className="tabular min-h-6 text-md font-medium">{item.value}</dd>
          </div>
        ))}
      </dl>
      <DataTable
        caption={copy.title}
        columns={columns}
        rows={list.data?.items}
        rowId={(row) => row.id}
        loading={list.isLoading}
        error={list.isError ? copy.loadFailed : null}
        onRetry={() => void list.refetch()}
        sort={sort}
        onSortChange={(next) => setParams({ sort: next ? `${next.field}:${next.dir}` : "" })}
        onRowClick={(row) => navigate(`/sales/${row.id}`)}
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
