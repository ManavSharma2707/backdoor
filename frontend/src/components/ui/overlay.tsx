import type { ReactNode } from "react";
import { Dialog as D, DropdownMenu as M, Popover as P, Tooltip as T } from "radix-ui";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import { common } from "@/copy/common";
import { Button } from "./button";

// ------------------------------------------------------------------ tooltip

export const TooltipProvider = ({ children }: { children: ReactNode }) => (
  <T.Provider delayDuration={300} skipDelayDuration={100}>
    {children}
  </T.Provider>
);

/** Never the only place important information lives. */
export function Tip({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          sideOffset={6}
          className="fade-in z-50 max-w-64 rounded-md bg-text px-2.5 py-1.5 text-xs text-text-inverse shadow-popover"
        >
          {label}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

// ------------------------------------------------------------------ dialog

type DialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
};

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  wide,
}: DialogProps) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fade-in fixed inset-0 z-40 bg-text/30" />
        <D.Content
          aria-describedby={description ? undefined : undefined}
          className={cn(
            "dialog-in fixed top-1/2 left-1/2 z-50 flex max-h-[90dvh] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-border bg-surface shadow-dialog",
            wide ? "max-w-[560px]" : "max-w-[480px]",
          )}
        >
          <div className="flex items-start justify-between gap-4 px-5 pt-5">
            <div className="min-w-0">
              <D.Title className="text-lg font-semibold">{title}</D.Title>
              {description ? (
                <D.Description className="mt-1 text-base text-text-2">{description}</D.Description>
              ) : null}
            </div>
            <D.Close asChild>
              <Button
                variant="ghost"
                size="sm"
                aria-label={common.close}
                className="-mt-1 -mr-2 px-2"
              >
                <X size={16} strokeWidth={1.5} />
              </Button>
            </D.Close>
          </div>
          {children ? (
            <div className="overflow-y-auto px-5 py-4">{children}</div>
          ) : (
            <div className="h-4" />
          )}
          {footer ? (
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>
          ) : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

type ConfirmProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  loading?: boolean;
  destructive?: boolean;
  children?: ReactNode;
};

/** Names the thing being changed and what happens. The confirm button repeats the action. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  onConfirm,
  loading,
  destructive,
  children,
}: ConfirmProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={body}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>{common.cancel}</Button>
          <Button
            variant={destructive ? "destructive-filled" : "primary"}
            loading={loading}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}

// ------------------------------------------------------------------ drawer

export function Drawer({
  open,
  onOpenChange,
  title,
  children,
  side = "right",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  side?: "right" | "left";
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fade-in fixed inset-0 z-40 bg-text/30" />
        <D.Content
          aria-describedby={undefined}
          className={cn(
            "drawer-in fixed inset-y-0 z-50 flex w-[480px] max-w-full flex-col border-border bg-surface shadow-dialog",
            side === "right" ? "right-0 border-l" : "left-0 w-[280px] border-r",
          )}
        >
          <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
            <D.Title className="text-md font-medium">{title}</D.Title>
            <D.Close asChild>
              <Button variant="ghost" size="sm" aria-label={common.close} className="px-2">
                <X size={16} strokeWidth={1.5} />
              </Button>
            </D.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

// ------------------------------------------------------------------ popover and menu

export const Popover = P.Root;
export const PopoverTrigger = P.Trigger;
export function PopoverContent({
  className,
  children,
  align = "start",
}: {
  className?: string;
  children: ReactNode;
  align?: "start" | "end" | "center";
}) {
  return (
    <P.Portal>
      <P.Content
        align={align}
        sideOffset={6}
        className={cn(
          "fade-in z-50 rounded-md border border-border bg-surface p-3 shadow-popover",
          className,
        )}
      >
        {children}
      </P.Content>
    </P.Portal>
  );
}

export type MenuItem = {
  label: string;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
};

/** An overflow menu. The trigger is whatever button you pass in. */
export function Menu({
  trigger,
  items,
  align = "end",
}: {
  trigger: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
}) {
  return (
    <M.Root>
      <M.Trigger asChild>{trigger}</M.Trigger>
      <M.Portal>
        <M.Content
          align={align}
          sideOffset={6}
          className="fade-in z-50 min-w-44 rounded-md border border-border bg-surface p-1 shadow-popover"
        >
          {items.map((item) => (
            <M.Item
              key={item.label}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className={cn(
                "flex h-8 cursor-pointer items-center rounded-sm px-2.5 text-base outline-none select-none",
                "data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2",
                item.destructive ? "text-critical" : "text-text",
              )}
            >
              {item.label}
            </M.Item>
          ))}
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}
