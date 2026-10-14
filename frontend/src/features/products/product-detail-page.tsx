import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { errorText } from "@/lib/forms";
import { useQueryParams } from "@/lib/hooks";
import { useApiQuery } from "@/lib/queries";
import { formatDate, formatDateTime, money, percentValue, quantity } from "@/lib/format";
import { products as copy } from "@/copy/products";
import type { Page, PriceHistory, Product, ProductStock, SaleListItem } from "@/types/models";
import { Button } from "@/components/ui/button";
import { TabPanel, Tabs } from "@/components/ui/controls";
import {
  Banner,
  EmptyState,
  KeyValueList,
  Mono,
  PageHeader,
  Panel,
  Skeleton,
  Stat,
  StatusChip,
} from "@/components/ui/display";
import { ConfirmDialog } from "@/components/ui/overlay";
import { DataTable, type Column } from "@/components/ui/table";
import { notify } from "@/components/ui/pickers";
import { AdjustmentDialog } from "@/features/stock/adjustment-dialog";

const yesNo = (value: boolean) => (value ? copy.detail.yes : copy.detail.no);

function DetailsTab({ product, medical }: { product: Product; medical: boolean }) {
  const rows = [
    { label: copy.detail.sku, value: <Mono>{product.sku}</Mono> },
    { label: copy.detail.barcode, value: product.barcode ? <Mono>{product.barcode}</Mono> : "" },
    { label: copy.detail.brand, value: product.brand ?? "" },
    { label: copy.detail.category, value: product.category_name },
    {
      label: copy.detail.unit,
      value: [copy.unitName(product.base_unit), product.pack_label].filter(Boolean).join(", "),
    },
    { label: copy.detail.mrp, value: money(product.mrp, 2) },
    { label: copy.detail.price, value: money(product.selling_price, 2) },
    { label: copy.detail.gst, value: percentValue(product.tax_rate_pct) },
    { label: copy.detail.batchTracked, value: yesNo(product.is_batch_tracked) },
    {
      label: copy.form.shelfLife,
      value: product.shelf_life_days ? copy.detail.shelfLife(product.shelf_life_days) : "",
    },
    { label: copy.detail.minStock, value: quantity(product.min_stock_qty) },
    { label: copy.detail.seasonal, value: yesNo(product.is_seasonal) },
    { label: copy.detail.launched, value: formatDate(product.launched_on) },
    { label: copy.detail.supplier, value: product.primary_supplier_name ?? "" },
    ...(medical
      ? [
          { label: copy.detail.generic, value: product.generic_name ?? "" },
          { label: copy.detail.strength, value: product.strength ?? "" },
          { label: copy.detail.form, value: product.dosage_form ?? "" },
          { label: copy.detail.manufacturer, value: product.manufacturer ?? "" },
          { label: copy.detail.schedule, value: product.schedule_class ?? "" },
        ]
      : []),
    { label: copy.detail.notes, value: product.notes ?? "" },
  ].filter((row) => row.value !== "");
  return (
    <Panel className="max-w-3xl">
      <KeyValueList rows={rows} />
    </Panel>
  );
}

function StockTab({ product, stock }: { product: Product; stock: ProductStock | undefined }) {
  return (
    <Panel className="max-w-3xl">
      {!stock ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-3">
          <Stat label={copy.detail.onHand} value={quantity(stock.on_hand)} />
          <Stat label={copy.detail.sellable} value={quantity(stock.sellable)} />
          <Stat label={copy.detail.value} value={money(stock.value)} />
        </div>
      )}
      {!product.is_batch_tracked ? (
        <p className="mt-4 text-sm text-text-2">{copy.detail.stockNote}</p>
      ) : null}
    </Panel>
  );
}

function BatchesTab({ stock }: { stock: ProductStock | undefined }) {
  const columns: Column<ProductStock["batches"][number]>[] = [
    { key: "batch", header: copy.detail.batchNo, cell: (b) => <Mono>{b.batch_no}</Mono> },
    { key: "expiry", header: copy.detail.expiry, cell: (b) => formatDate(b.expiry_date) },
    {
      key: "days",
      header: copy.detail.daysLeft,
      numeric: true,
      cell: (b) => (b.is_expired ? copy.detail.expired : quantity(b.days_to_expiry)),
    },
    { key: "qty", header: copy.detail.quantity, numeric: true, cell: (b) => quantity(b.on_hand) },
    {
      key: "value",
      header: copy.detail.batchValue,
      unit: "₹",
      numeric: true,
      cell: (b) => money(b.value).replace("₹", ""),
    },
    {
      key: "first",
      header: copy.detail.sellFirst,
      cell: (b) =>
        b.sell_first ? <StatusChip tone="info">{copy.detail.sellFirst}</StatusChip> : null,
    },
  ];
  return (
    <DataTable
      caption={copy.detail.tabs.batches}
      columns={columns}
      rows={stock?.batches}
      rowId={(b) => b.batch_id}
      loading={!stock}
      empty={<EmptyState title={copy.detail.noBatches} hint={copy.detail.noBatchesHint} />}
    />
  );
}

function PricesTab({ id }: { id: string }) {
  const prices = useApiQuery<PriceHistory[]>(`/products/${id}/prices`);
  const columns: Column<PriceHistory>[] = [
    { key: "from", header: copy.detail.priceFrom, cell: (p) => formatDate(p.effective_from) },
    {
      key: "to",
      header: copy.detail.priceTo,
      cell: (p) => (p.effective_to ? formatDate(p.effective_to) : copy.detail.priceCurrent),
    },
    {
      key: "mrp",
      header: copy.detail.priceMrp,
      unit: "₹",
      numeric: true,
      cell: (p) => money(p.mrp, 2).replace("₹", ""),
    },
    {
      key: "sell",
      header: copy.detail.priceSelling,
      unit: "₹",
      numeric: true,
      cell: (p) => money(p.selling_price, 2).replace("₹", ""),
    },
    { key: "reason", header: copy.detail.priceReason, cell: (p) => p.reason ?? "" },
  ];
  return (
    <DataTable
      caption={copy.detail.tabs.prices}
      columns={columns}
      rows={prices.data}
      rowId={(p) => p.id}
      loading={prices.isLoading}
      empty={<EmptyState title={copy.detail.noPrices} />}
    />
  );
}

function SalesTab({ id }: { id: string }) {
  const navigate = useNavigate();
  const sales = useApiQuery<Page<SaleListItem>>("/sales", { product_id: id, page_size: 20 });
  const columns: Column<SaleListItem>[] = [
    {
      key: "bill",
      header: copy.detail.salesBill,
      cell: (s) => (
        <Link to={`/sales/${s.id}`} className="font-mono text-sm hover:underline">
          {s.bill_no}
        </Link>
      ),
    },
    { key: "date", header: copy.detail.salesDate, cell: (s) => formatDateTime(s.sold_at) },
    { key: "items", header: copy.detail.salesItems, numeric: true, cell: (s) => quantity(s.items) },
    {
      key: "total",
      header: copy.detail.salesTotal,
      unit: "₹",
      numeric: true,
      cell: (s) => money(s.total, 2).replace("₹", ""),
    },
  ];
  return (
    <DataTable
      caption={copy.detail.tabs.sales}
      columns={columns}
      rows={sales.data?.items}
      rowId={(s) => s.id}
      loading={sales.isLoading}
      onRowClick={(s) => navigate(`/sales/${s.id}`)}
      empty={<EmptyState title={copy.detail.noSales} />}
    />
  );
}

export default function ProductDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const { tenant } = useSession();
  const medical = tenant.business_type === "medical";
  const [params, setParams] = useQueryParams({ tab: "details" });
  const [adjusting, setAdjusting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const product = useApiQuery<Product>(`/products/${id}`);
  const stock = useApiQuery<ProductStock>(`/products/${id}/stock`);

  const toggle = useMutation({
    mutationFn: (activate: boolean) =>
      post<Product>(`/products/${id}/${activate ? "activate" : "deactivate"}`),
    onSuccess: (_data, activate) => {
      notify.success(activate ? copy.detail.activated : copy.detail.deactivated);
      setConfirming(false);
      void queryClient.invalidateQueries();
    },
    onError: (error) => {
      setConfirming(false);
      notify.error(errorText(error));
    },
  });

  if (product.isLoading) return <Skeleton className="h-64 w-full" />;
  if (product.isError || !product.data) {
    return <Banner tone="error">{copy.detail.notFound}</Banner>;
  }
  const p = product.data;
  const tabs = [
    { value: "details", label: copy.detail.tabs.details },
    { value: "stock", label: copy.detail.tabs.stock },
    ...(p.is_batch_tracked ? [{ value: "batches", label: copy.detail.tabs.batches }] : []),
    { value: "prices", label: copy.detail.tabs.prices },
    { value: "sales", label: copy.detail.tabs.sales },
  ];
  const tab = tabs.some((t) => t.value === params.tab) ? params.tab : "details";

  return (
    <>
      <PageHeader
        title={p.name}
        context={
          <span className="inline-flex flex-wrap items-center gap-2">
            <Mono>{p.sku}</Mono>
            <span>{p.category_name}</span>
            {!p.is_active ? <StatusChip>{copy.inactive}</StatusChip> : null}
          </span>
        }
        actions={
          <>
            <Link to={`/products/${p.id}/edit`}>
              <Button>{copy.detail.edit}</Button>
            </Link>
            <Button onClick={() => setAdjusting(true)}>{copy.detail.adjust}</Button>
            {p.is_active ? (
              <Button variant="destructive" onClick={() => setConfirming(true)}>
                {copy.detail.deactivate}
              </Button>
            ) : (
              <Button loading={toggle.isPending} onClick={() => toggle.mutate(true)}>
                {copy.detail.activate}
              </Button>
            )}
          </>
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-6 rounded-md border border-border bg-surface px-4 py-3 sm:grid-cols-4">
        <Stat label={copy.detail.onHand} value={quantity(p.on_hand)} />
        <Stat
          label={copy.detail.price}
          value={money(p.selling_price, 2)}
          hint={`${copy.detail.mrp} ${money(p.mrp, 2)}`}
        />
        {p.days_of_cover === null ? null : (
          <Stat label={copy.detail.cover} value={quantity(p.days_of_cover)} />
        )}
        <Stat label={copy.detail.supplier} value={p.primary_supplier_name ?? ""} />
      </div>
      <Tabs
        label={copy.title}
        value={tab}
        onValueChange={(value) => setParams({ tab: value })}
        items={tabs}
      >
        <TabPanel value="details">
          <DetailsTab product={p} medical={medical} />
        </TabPanel>
        <TabPanel value="stock">
          <StockTab product={p} stock={stock.data} />
        </TabPanel>
        <TabPanel value="batches">
          <BatchesTab stock={stock.data} />
        </TabPanel>
        <TabPanel value="prices">
          <PricesTab id={p.id} />
        </TabPanel>
        <TabPanel value="sales">
          <SalesTab id={p.id} />
        </TabPanel>
      </Tabs>
      <AdjustmentDialog open={adjusting} onOpenChange={setAdjusting} product={p} />
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={copy.detail.deactivateTitle(p.name)}
        body={copy.detail.deactivateBody}
        confirmLabel={copy.detail.deactivate}
        destructive
        loading={toggle.isPending}
        onConfirm={() => toggle.mutate(false)}
      />
    </>
  );
}
