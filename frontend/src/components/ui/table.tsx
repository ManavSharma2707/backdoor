import type { ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { common } from "@/copy/common";
import { Button } from "./button";
import { Select } from "./field";
import { ErrorBanner, Skeleton } from "./display";

export type SortState = { field: string; dir: "asc" | "desc" } | null;

export type Column<Row> = {
  key: string;
  header: string;
  /** Unit shown once in the header, for example "packs" or "₹". */
  unit?: string;
  cell: (row: Row, index: number) => ReactNode;
  /** Right aligned, tabular numbers. */
  numeric?: boolean;
  /** Text only in the header for screen readers. */
  headerHidden?: boolean;
  sortField?: string;
  className?: string;
  width?: string;
};

type TableProps<Row> = {
  caption: string;
  columns: Column<Row>[];
  rows: Row[] | undefined;
  rowId: (row: Row) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  retryLabel?: string;
  empty?: ReactNode;
  sort?: SortState;
  onSortChange?: (sort: SortState) => void;
  onRowClick?: (row: Row) => void;
  selectedId?: string | null;
  compact?: boolean;
  footer?: ReactNode;
  skeletonRows?: number;
  rowClassName?: (row: Row) => string | undefined;
};

/** Dense table with a sticky header. The first column stays in view on small screens. */
export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowId,
  loading,
  error,
  onRetry,
  retryLabel = common.retry,
  empty,
  sort,
  onSortChange,
  onRowClick,
  selectedId,
  compact,
  footer,
  skeletonRows = 8,
  rowClassName,
}: TableProps<Row>) {
  const rowHeight = compact ? "h-8" : "h-10";
  const showSkeleton = loading && (!rows || rows.length === 0);
  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface">
      {error ? (
        <div className="p-3">
          <ErrorBanner message={error} onRetry={onRetry} retryLabel={retryLabel} />
        </div>
      ) : null}
      <div className="max-h-[70dvh] overflow-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr>
              {columns.map((column, index) => {
                const active = sort && column.sortField && sort.field === column.sortField;
                const sortable = Boolean(column.sortField && onSortChange);
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={
                      active ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined
                    }
                    style={column.width ? { width: column.width } : undefined}
                    className={cn(
                      "h-9 border-b border-border px-3 text-xs font-medium whitespace-nowrap text-text-2",
                      column.numeric ? "text-right" : "text-left",
                      index === 0 && "sticky left-0 z-10 bg-surface-2",
                    )}
                  >
                    <span className={column.headerHidden ? "sr-only" : undefined}>
                      {sortable ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:text-text"
                          onClick={() => {
                            const field = column.sortField as string;
                            if (!active) onSortChange?.({ field, dir: "asc" });
                            else if (sort?.dir === "asc") onSortChange?.({ field, dir: "desc" });
                            else onSortChange?.(null);
                          }}
                          aria-label={common.sortBy(column.header)}
                        >
                          {column.header}
                          {column.unit ? (
                            <span className="font-normal text-text-3">({column.unit})</span>
                          ) : null}
                          {active ? (
                            sort?.dir === "asc" ? (
                              <ChevronUp size={12} strokeWidth={1.5} />
                            ) : (
                              <ChevronDown size={12} strokeWidth={1.5} />
                            )
                          ) : null}
                        </button>
                      ) : (
                        <>
                          {column.header}
                          {column.unit ? (
                            <span className="ml-1 font-normal text-text-3">({column.unit})</span>
                          ) : null}
                        </>
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {showSkeleton
              ? Array.from({ length: skeletonRows }, (_, r) => (
                  <tr key={r} className={cn(rowHeight, "border-b border-border")}>
                    {columns.map((column, c) => (
                      <td
                        key={column.key}
                        className={cn("px-3", c === 0 && "sticky left-0 bg-surface")}
                      >
                        <Skeleton
                          className={cn("h-3", column.numeric ? "ml-auto w-12" : "w-3/4")}
                        />
                      </td>
                    ))}
                  </tr>
                ))
              : null}
            {!showSkeleton && rows?.length
              ? rows.map((row, index) => {
                  const id = rowId(row);
                  const clickable = Boolean(onRowClick);
                  return (
                    <tr
                      key={id}
                      aria-selected={selectedId === id || undefined}
                      onClick={clickable ? () => onRowClick?.(row) : undefined}
                      className={cn(
                        rowHeight,
                        "group border-b border-border last:border-b-0 hover:bg-surface-2",
                        selectedId === id && "bg-surface-3",
                        clickable && "cursor-pointer",
                        rowClassName?.(row),
                      )}
                    >
                      {columns.map((column, c) => (
                        <td
                          key={column.key}
                          className={cn(
                            "px-3 align-middle",
                            column.numeric && "tabular text-right",
                            c === 0 &&
                              "sticky left-0 bg-surface group-hover:bg-surface-2 group-aria-selected:bg-surface-3",
                            column.className,
                          )}
                        >
                          {column.cell(row, index)}
                        </td>
                      ))}
                    </tr>
                  );
                })
              : null}
          </tbody>
        </table>
        {!showSkeleton && !error && rows && rows.length === 0 ? empty : null}
      </div>
      {footer}
    </div>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  sizes = [25, 50, 100],
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  sizes?: number[];
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-3 py-2 text-sm text-text-2">
      <span className="tabular" aria-live="polite">
        {common.rangeOf(from, to, total)}
      </span>
      <div className="flex items-center gap-2">
        {onPageSizeChange ? (
          <div className="w-20">
            <Select
              aria-label={common.pageSize}
              value={pageSize}
              onChange={(event) => onPageSizeChange(Number(event.target.value))}
              className="h-8"
            >
              {sizes.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </Select>
          </div>
        ) : null}
        <Button size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          {common.previous}
        </Button>
        <Button size="sm" disabled={to >= total} onClick={() => onPageChange(page + 1)}>
          {common.next}
        </Button>
      </div>
    </div>
  );
}
