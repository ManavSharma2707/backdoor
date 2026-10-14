import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { get, post } from "@/lib/api";
import { errorText } from "@/lib/forms";
import { newKey, useDebounced } from "@/lib/hooks";
import { useApiQuery } from "@/lib/queries";
import { formatDate, money, quantity } from "@/lib/format";
import { common } from "@/copy/common";
import { sales as copy } from "@/copy/sales";
import type { Page, Product, ProductStock, Sale, SaleCreate } from "@/types/models";
import { Button, TextButton } from "@/components/ui/button";
import { Segmented } from "@/components/ui/controls";
import { Banner, EmptyState, Mono, PageHeader, Panel } from "@/components/ui/display";
import { Input, NumberInput, Select } from "@/components/ui/field";
import { notify } from "@/components/ui/pickers";
import { cn } from "@/lib/cn";
import {
  addProduct,
  availableFor,
  billTotalText,
  exceedsStock,
  hasProblems,
  lineTotalText,
  problemsFor,
  toRequest,
  type EntryLine,
} from "./entry-model";

const PAYMENT_OPTIONS = (["cash", "upi", "card", "credit"] as const).map((value) => ({
  value,
  label: copy.payment[value],
}));

export default function SaleEntryPage() {
  const queryClient = useQueryClient();
  const searchRef = useRef<HTMLInputElement>(null);
  const keyRef = useRef(newKey());
  const [lines, setLines] = useState<EntryLine[]>([]);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [payment, setPayment] = useState<SaleCreate["payment_mode"]>("cash");
  const [showProblems, setShowProblems] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<Sale | null>(null);

  const debounced = useDebounced(query.trim(), 150);
  const results = useApiQuery<Page<Product>>(
    "/products",
    { q: debounced, page_size: 8 },
    {
      enabled: debounced.length > 0,
    },
  );
  const items = debounced === query.trim() ? (results.data?.items ?? []) : [];

  useEffect(() => searchRef.current?.focus(), []);
  useEffect(() => setActive(0), [debounced]);

  const loadBatches = useCallback(
    async (product: Product) => {
      if (!product.is_batch_tracked) return;
      try {
        const stock = await queryClient.fetchQuery({
          queryKey: [`/products/${product.id}/stock`, {}],
          queryFn: () => get<ProductStock>(`/products/${product.id}/stock`),
          staleTime: 15_000,
        });
        setLines((current) =>
          current.map((line) =>
            line.product.id === product.id ? { ...line, batches: stock.batches } : line,
          ),
        );
      } catch {
        // The server still picks the earliest expiry batch when none is chosen.
      }
    },
    [queryClient],
  );

  const add = useCallback(
    (product: Product) => {
      setLines((current) => addProduct(current, product));
      void loadBatches(product);
      setQuery("");
      setDuplicate(null);
      setFormError(null);
      searchRef.current?.focus();
    },
    [loadBatches],
  );

  const addFromEnter = async () => {
    const text = query.trim();
    if (!text) {
      const fields = document.querySelectorAll<HTMLInputElement>("[data-qty]");
      const last = fields[fields.length - 1];
      last?.focus();
      last?.select();
      return;
    }
    let found = items;
    let pick = found[active];
    if (found.length === 0) {
      const fresh = await queryClient.fetchQuery({
        queryKey: ["/products", { q: text, page_size: 8 }],
        queryFn: () => get<Page<Product>>("/products", { q: text, page_size: 8 }),
        staleTime: 10_000,
      });
      found = fresh.items;
      pick = found[0];
    }
    const exact = found.find(
      (p) => p.barcode === text || p.sku.toLowerCase() === text.toLowerCase(),
    );
    const choice = exact ?? pick;
    if (choice) add(choice);
  };

  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(items.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      void addFromEnter();
    } else if (event.key === "Escape") {
      setQuery("");
    }
  };

  const update = (key: string, patch: Partial<EntryLine>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  const save = useMutation({
    mutationFn: () =>
      post<Sale>("/sales", toRequest(lines, payment), { idempotencyKey: keyRef.current }),
    onSuccess: (sale) => {
      notify.success(copy.entry.saved);
      keyRef.current = newKey();
      setLines([]);
      setShowProblems(false);
      setFormError(null);
      setDuplicate(sale.warnings?.some((w) => w.code === "POSSIBLE_DUPLICATE") ? sale : null);
      void queryClient.invalidateQueries();
      searchRef.current?.focus();
    },
    onError: (error) => setFormError(errorText(error)),
  });

  const voidDuplicate = useMutation({
    mutationFn: (sale: Sale) => post(`/sales/${sale.id}/void`, { reason: copy.entry.duplicate }),
    onSuccess: () => {
      notify.success(copy.entry.voided);
      setDuplicate(null);
      void queryClient.invalidateQueries();
    },
    onError: (error) => notify.error(errorText(error)),
  });

  const submit = useCallback(() => {
    setFormError(null);
    if (lines.length === 0) {
      setFormError(copy.entry.nothing);
      return;
    }
    if (lines.some((line) => hasProblems(problemsFor(line)))) {
      setShowProblems(true);
      setFormError(copy.entry.invalidLine);
      return;
    }
    save.mutate();
  }, [lines, save]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [submit]);

  const total = billTotalText(lines);

  return (
    <>
      <PageHeader
        title={copy.entry.title}
        actions={
          <Link to="/sales">
            <Button variant="ghost">{common.back}</Button>
          </Link>
        }
      />
      {duplicate ? (
        <Banner
          tone="warning"
          className="mb-4"
          action={
            <span className="flex gap-2">
              <Link to={`/sales/${duplicate.id}`}>
                <Button size="sm">{copy.entry.openEarlier}</Button>
              </Link>
              <Button
                size="sm"
                variant="destructive"
                loading={voidDuplicate.isPending}
                onClick={() => voidDuplicate.mutate(duplicate)}
              >
                {copy.entry.voidThis}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDuplicate(null)}>
                {copy.entry.keepBoth}
              </Button>
            </span>
          }
        >
          {copy.entry.duplicate}
        </Banner>
      ) : null}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-4">
          <div className="relative">
            <Search
              size={16}
              strokeWidth={1.5}
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
            />
            <Input
              ref={searchRef}
              role="combobox"
              aria-expanded={items.length > 0}
              aria-controls="sale-results"
              aria-activedescendant={items[active] ? `sale-result-${items[active].id}` : undefined}
              aria-label={copy.entry.searchLabel}
              placeholder={copy.entry.searchPlaceholder}
              autoComplete="off"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onSearchKey}
              className="h-11 pl-10 text-md"
            />
            {query.trim() ? (
              <ul
                id="sale-results"
                role="listbox"
                aria-label={copy.entry.searchLabel}
                className="absolute z-20 mt-1 max-h-80 w-full overflow-y-auto rounded-md border border-border bg-surface py-1 shadow-popover"
              >
                {items.length === 0 ? (
                  <li role="presentation" className="px-3 py-2 text-sm text-text-3">
                    {results.isFetching || debounced !== query.trim()
                      ? copy.entry.searching
                      : copy.entry.noMatch}
                  </li>
                ) : (
                  items.map((product, index) => (
                    <li
                      key={product.id}
                      id={`sale-result-${product.id}`}
                      role="option"
                      aria-selected={index === active}
                      onMouseEnter={() => setActive(index)}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        add(product);
                      }}
                      className={cn(
                        "flex cursor-pointer items-center justify-between gap-3 px-3 py-2",
                        index === active && "bg-surface-2",
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-base">{product.name}</span>
                        <Mono className="text-text-3">{product.sku}</Mono>
                      </span>
                      <span className="shrink-0 text-right text-sm">
                        <span className="tabular block">{money(product.selling_price, 2)}</span>
                        <span
                          className={cn(
                            "block text-xs",
                            Number(product.on_hand) <= 0 ? "text-critical" : "text-text-3",
                          )}
                        >
                          {Number(product.on_hand) <= 0
                            ? copy.entry.outOfStock
                            : copy.entry.inStock(quantity(product.on_hand))}
                        </span>
                      </span>
                    </li>
                  ))
                )}
              </ul>
            ) : null}
          </div>

          <div className="overflow-x-auto rounded-md border border-border bg-surface">
            <table className="w-full border-collapse text-sm">
              <caption className="sr-only">{copy.entry.title}</caption>
              <thead className="bg-surface-2 text-xs text-text-2">
                <tr>
                  <th scope="col" className="h-9 px-3 text-left font-medium">
                    {copy.entry.columns.product}
                  </th>
                  <th scope="col" className="h-9 px-3 text-left font-medium">
                    {copy.entry.columns.batch}
                  </th>
                  <th scope="col" className="h-9 w-24 px-3 text-right font-medium">
                    {copy.entry.columns.quantity}
                  </th>
                  <th scope="col" className="h-9 w-28 px-3 text-right font-medium">
                    {copy.entry.columns.price} (₹)
                  </th>
                  <th scope="col" className="h-9 w-24 px-3 text-right font-medium">
                    {copy.entry.columns.discount} (₹)
                  </th>
                  <th scope="col" className="h-9 w-28 px-3 text-right font-medium">
                    {copy.entry.columns.total} (₹)
                  </th>
                  <th scope="col" className="h-9 w-10 px-1">
                    <span className="sr-only">{copy.entry.columns.remove}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => {
                  const problems = showProblems ? problemsFor(line) : {};
                  const lt = lineTotalText(line);
                  const sellFirst = line.batches?.find((b) => b.sell_first);
                  return (
                    <tr key={line.key} className="border-t border-border align-top">
                      <td className="px-3 py-2">
                        <div className="font-medium">{line.product.name}</div>
                        <Mono className="text-text-3">{line.product.sku}</Mono>
                        {exceedsStock(line) ? (
                          <div role="alert" className="mt-1 text-xs text-high">
                            {copy.entry.onlyLeft(quantity(availableFor(line)), line.product.name)}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        {line.product.is_batch_tracked ? (
                          <div className="w-44">
                            <Select
                              aria-label={copy.entry.batchLabel(line.product.name)}
                              value={line.batchId}
                              onChange={(e) => update(line.key, { batchId: e.target.value })}
                              className="h-8"
                            >
                              <option value="">{copy.entry.batchAuto}</option>
                              {(line.batches ?? []).map((b) => (
                                <option key={b.batch_id} value={b.batch_id}>
                                  {copy.entry.batchOption(
                                    b.batch_no,
                                    formatDate(b.expiry_date),
                                    quantity(b.on_hand),
                                  )}
                                </option>
                              ))}
                            </Select>
                            {!line.batchId && sellFirst ? (
                              <div className="mt-1 text-xs text-text-3">
                                {copy.entry.nextBatch(formatDate(sellFirst.expiry_date))}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <NumberInput
                          data-qty
                          aria-label={copy.entry.quantityLabel(line.product.name)}
                          aria-invalid={problems.quantity ? true : undefined}
                          value={line.quantity}
                          onChange={(e) => update(line.key, { quantity: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
                              e.preventDefault();
                              searchRef.current?.focus();
                            }
                          }}
                          className="h-8"
                        />
                        {problems.quantity ? (
                          <div className="mt-1 text-xs text-critical">
                            {copy.entry.lineError.quantity}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <NumberInput
                          aria-label={copy.entry.priceLabel(line.product.name)}
                          aria-invalid={problems.price ? true : undefined}
                          value={line.price}
                          onChange={(e) => update(line.key, { price: e.target.value })}
                          className="h-8"
                        />
                        {problems.price ? (
                          <div className="mt-1 text-xs text-critical">
                            {copy.entry.lineError.price}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <NumberInput
                          aria-label={copy.entry.discountLabel(line.product.name)}
                          aria-invalid={problems.discount ? true : undefined}
                          value={line.discount}
                          placeholder="0"
                          onChange={(e) => update(line.key, { discount: e.target.value })}
                          className="h-8"
                        />
                        {problems.discount ? (
                          <div className="mt-1 text-xs text-critical">
                            {copy.entry.lineError.discount}
                          </div>
                        ) : null}
                      </td>
                      <td className="tabular px-3 py-2 pt-3 text-right">
                        {lt === null ? "" : money(lt, 2).replace("₹", "")}
                      </td>
                      <td className="px-1 py-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="px-2"
                          aria-label={copy.entry.removeLine(line.product.name)}
                          onClick={() =>
                            setLines((current) => current.filter((l) => l.key !== line.key))
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
            {lines.length === 0 ? (
              <EmptyState title={copy.entry.emptyLines} hint={copy.entry.emptyLinesHint} />
            ) : null}
          </div>
        </div>

        <Panel className="lg:sticky lg:top-6">
          <div className="space-y-4">
            <div>
              <div className="text-sm text-text-2">{copy.entry.total}</div>
              <div className="tabular text-kpi font-semibold">{money(total, 2)}</div>
              <div className="text-xs text-text-3">{copy.entry.items(lines.length)}</div>
            </div>
            <div>
              <div className="mb-1 text-sm font-medium">{copy.entry.paymentMode}</div>
              <Segmented
                label={copy.entry.paymentMode}
                value={payment}
                onValueChange={setPayment}
                options={PAYMENT_OPTIONS}
                className="w-full"
              />
            </div>
            {formError ? (
              <p role="alert" className="text-sm text-critical">
                {formError}
              </p>
            ) : null}
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              loading={save.isPending}
              onClick={submit}
            >
              {copy.entry.save}
            </Button>
            <p className="text-center text-xs text-text-3">{copy.entry.saveHint}</p>
            {lines.length > 0 ? (
              <TextButton
                className="block w-full text-center text-text-2"
                onClick={() => setLines([])}
              >
                {common.clear}
              </TextButton>
            ) : null}
          </div>
        </Panel>
      </div>
    </>
  );
}
