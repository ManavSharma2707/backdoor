import { useState } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "@/lib/api";
import { errorText } from "@/lib/forms";
import { useApiQuery } from "@/lib/queries";
import { formatDate, formatDateTime, money, quantity } from "@/lib/format";
import { common } from "@/copy/common";
import { purchases as copy } from "@/copy/purchases";
import type { PurchaseLine, PurchaseOrder, Receipt } from "@/types/models";
import { Button } from "@/components/ui/button";
import {
  Banner,
  KeyValueList,
  Mono,
  PageHeader,
  Panel,
  Skeleton,
  StatusChip,
} from "@/components/ui/display";
import { TextareaField } from "@/components/ui/field";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { notify } from "@/components/ui/pickers";
import { DataTable, type Column } from "@/components/ui/table";
import { STATUS_TONE } from "./purchases-page";
import { ReceiptDialog } from "./receipt-dialog";

function Timeline({ order }: { order: PurchaseOrder }) {
  return (
    <ol className="space-y-3">
      {order.timeline.map((event, index) => (
        <li key={`${event.event}-${index}`} className="flex items-baseline gap-3 text-base">
          <span
            className="size-2 shrink-0 translate-y-[-1px] rounded-full bg-primary"
            aria-hidden="true"
          />
          <span className="font-medium">
            {event.event === "received"
              ? copy.detail.steps.received
              : copy.detail.steps[event.event]}
          </span>
          <span className="text-sm text-text-3">{formatDateTime(event.at)}</span>
          {event.detail ? <span className="text-sm text-text-2">{event.detail}</span> : null}
        </li>
      ))}
    </ol>
  );
}

export default function PurchaseDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const order = useApiQuery<PurchaseOrder>(`/purchase-orders/${id}`);
  const [receiving, setReceiving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [closing, setClosing] = useState(false);
  const [reason, setReason] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);

  const transition = useMutation({
    mutationFn: ({ action, body }: { action: "send" | "cancel" | "close"; body?: unknown }) =>
      post<PurchaseOrder>(`/purchase-orders/${id}/${action}`, body),
    onSuccess: (_data, { action }) => {
      notify.success(
        action === "send"
          ? copy.detail.sent
          : action === "cancel"
            ? copy.detail.cancelled
            : copy.detail.closed,
      );
      setCancelling(false);
      setClosing(false);
      void queryClient.invalidateQueries();
    },
    onError: (error) => {
      setCancelling(false);
      setClosing(false);
      notify.error(errorText(error));
    },
  });

  if (order.isLoading) return <Skeleton className="h-64 w-full" />;
  if (order.isError || !order.data) return <Banner tone="error">{copy.detail.notFound}</Banner>;
  const o = order.data;
  const canReceive = o.status === "sent" || o.status === "partially_received";
  const canCancel = o.status === "draft" || o.status === "sent";
  const canClose =
    o.status === "sent" || o.status === "partially_received" || o.status === "received";

  const columns: Column<PurchaseLine>[] = [
    {
      key: "product",
      header: copy.detail.lines.product,
      className: "min-w-52",
      cell: (l) => (
        <div className="py-1">
          <Link to={`/products/${l.product_id}`} className="font-medium hover:underline">
            {l.product_name}
          </Link>
          <div>
            <Mono className="text-text-3">{l.product_sku}</Mono>
          </div>
        </div>
      ),
    },
    {
      key: "ordered",
      header: copy.detail.lines.ordered,
      numeric: true,
      cell: (l) => quantity(l.quantity_ordered),
    },
    {
      key: "received",
      header: copy.detail.lines.received,
      numeric: true,
      cell: (l) => quantity(l.quantity_received),
    },
    {
      key: "open",
      header: copy.detail.lines.open,
      numeric: true,
      cell: (l) => quantity(l.quantity_open),
    },
    {
      key: "cost",
      header: copy.detail.lines.cost,
      unit: "₹",
      numeric: true,
      cell: (l) => money(l.unit_cost, 2).replace("₹", ""),
    },
    {
      key: "value",
      header: copy.detail.lines.value,
      unit: "₹",
      numeric: true,
      cell: (l) => money(l.line_value, 2).replace("₹", ""),
    },
  ];

  return (
    <>
      <PageHeader
        title={copy.detail.title(o.po_number)}
        context={copy.detail.context(o.supplier_name, formatDate(o.order_date))}
        actions={
          <>
            <StatusChip tone={STATUS_TONE[o.status] ?? "neutral"}>
              {copy.status[o.status]}
            </StatusChip>
            {o.status === "draft" ? (
              <Button
                loading={transition.isPending && transition.variables?.action === "send"}
                onClick={() => transition.mutate({ action: "send" })}
              >
                {copy.detail.send}
              </Button>
            ) : null}
            {canReceive ? (
              <Button variant="primary" onClick={() => setReceiving(true)}>
                {copy.detail.receive}
              </Button>
            ) : null}
            {canClose ? (
              <Button onClick={() => setClosing(true)}>{copy.detail.close}</Button>
            ) : null}
            {canCancel ? (
              <Button variant="destructive" onClick={() => setCancelling(true)}>
                {copy.detail.cancel}
              </Button>
            ) : null}
          </>
        }
      />
      <div className="mb-4 space-y-3">
        {o.is_overdue ? (
          <Banner tone="warning">{copy.detail.lateBanner(o.days_late)}</Banner>
        ) : null}
        {o.status === "cancelled" ? (
          <Banner tone="info">
            {o.cancel_reason
              ? copy.detail.cancelledBanner(o.cancel_reason)
              : copy.detail.cancelledBannerNoReason}
          </Banner>
        ) : null}
        {warnings.length > 0 ? (
          <Banner
            tone="warning"
            action={
              <Button size="sm" variant="ghost" onClick={() => setWarnings([])}>
                {common.dismiss}
              </Button>
            }
          >
            <ul className="space-y-1">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Banner>
        ) : null}
      </div>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-6">
          <DataTable
            caption={copy.detail.title(o.po_number)}
            columns={columns}
            rows={o.lines}
            rowId={(l) => l.id}
          />
          <p className="text-right text-base">
            {copy.detail.total}:{" "}
            <span className="tabular font-semibold">{money(o.subtotal_estimated, 2)}</span>
          </p>
        </div>
        <div className="space-y-6">
          <Panel>
            <KeyValueList
              rows={[
                {
                  label: copy.detail.expected,
                  value: o.expected_date ? formatDate(o.expected_date) : "",
                },
                ...(o.notes ? [{ label: copy.newPage.notes, value: o.notes }] : []),
              ].filter((r) => r.value !== "")}
            />
          </Panel>
          <Panel title={copy.detail.timeline}>
            <Timeline order={o} />
          </Panel>
          <Panel title={copy.detail.receiptsTitle}>
            {o.receipts.length === 0 ? (
              <p className="text-base text-text-2">{copy.detail.noReceipts}</p>
            ) : (
              <ul className="space-y-3 text-base">
                {o.receipts.map((r) => (
                  <li key={r.id}>
                    <div>{copy.detail.receiptLine(r.receipt_no, formatDate(r.received_on))}</div>
                    <div className="text-sm text-text-2">
                      {money(r.lines_total, 2)}
                      {r.invoice_no ? `. ${copy.detail.receiptInvoice(r.invoice_no)}` : ""}
                      {r.is_exception ? `. ${copy.detail.receiptException}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
      <ReceiptDialog
        order={o}
        open={receiving}
        onOpenChange={setReceiving}
        onReceived={(receipt: Receipt) =>
          setWarnings((receipt.warnings ?? []).map((w) => w.message))
        }
      />
      <ConfirmDialog
        open={closing}
        onOpenChange={setClosing}
        title={copy.detail.closeTitle(o.po_number)}
        body={copy.detail.closeBody}
        confirmLabel={copy.detail.close}
        loading={transition.isPending}
        onConfirm={() => transition.mutate({ action: "close" })}
      />
      <Dialog
        open={cancelling}
        onOpenChange={setCancelling}
        title={copy.detail.cancelTitle(o.po_number)}
        description={copy.detail.cancelBody}
        footer={
          <>
            <Button onClick={() => setCancelling(false)}>{common.notNow}</Button>
            <Button
              variant="destructive-filled"
              loading={transition.isPending}
              onClick={() =>
                transition.mutate({
                  action: "cancel",
                  body: { reason: reason.trim() || undefined },
                })
              }
            >
              {copy.detail.cancel}
            </Button>
          </>
        }
      >
        <TextareaField
          label={copy.detail.cancelReason}
          optional
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Dialog>
    </>
  );
}
