import { useEffect, useState, type ReactNode } from "react";
import { Command } from "cmdk";
import { CalendarDays, ChevronLeft, ChevronRight, ChevronsUpDown } from "lucide-react";
import { Toaster, toast } from "sonner";
import { cn } from "@/lib/cn";
import { common } from "@/copy/common";
import { addDays, formatDate, parseTypedDate, todayIso } from "@/lib/format";
import { Button } from "./button";
import { Field, Input, NumberInput, controlClass } from "./field";
import { Popover, PopoverContent, PopoverTrigger } from "./overlay";

// ------------------------------------------------------------------ date picker

function monthGrid(year: number, month: number): (string | null)[] {
  const first = new Date(Date.UTC(year, month, 1));
  const lead = (first.getUTCDay() + 6) % 7; // Monday first
  const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= days; d++) {
    cells.push(`${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

function Calendar({
  value,
  onPick,
  min,
  max,
}: {
  value: string;
  onPick: (iso: string) => void;
  min?: string;
  max?: string;
}) {
  const start = value || todayIso();
  const [cursor, setCursor] = useState({
    year: Number(start.slice(0, 4)),
    month: Number(start.slice(5, 7)) - 1,
  });
  const today = todayIso();
  const shift = (by: number) =>
    setCursor(({ year, month }) => {
      const next = month + by;
      return { year: year + Math.floor(next / 12), month: ((next % 12) + 12) % 12 };
    });
  return (
    <div className="w-64">
      <div className="mb-2 flex items-center justify-between">
        <Button
          variant="ghost"
          size="sm"
          aria-label={common.date.previousMonth}
          onClick={() => shift(-1)}
          className="px-2"
        >
          <ChevronLeft size={16} strokeWidth={1.5} />
        </Button>
        <span className="text-base font-medium" aria-live="polite">
          {common.date.months[cursor.month]} {cursor.year}
        </span>
        <Button
          variant="ghost"
          size="sm"
          aria-label={common.date.nextMonth}
          onClick={() => shift(1)}
          className="px-2"
        >
          <ChevronRight size={16} strokeWidth={1.5} />
        </Button>
      </div>
      <div className="grid grid-cols-7 text-center text-xs text-text-3">
        {common.date.weekdays.map((weekday) => (
          <span key={weekday} className="py-1">
            {weekday}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-y-0.5">
        {monthGrid(cursor.year, cursor.month).map((iso, index) => {
          if (!iso) return <span key={`blank-${index}`} />;
          const disabled = Boolean((min && iso < min) || (max && iso > max));
          const selected = iso === value;
          return (
            <button
              key={iso}
              type="button"
              disabled={disabled}
              aria-label={formatDate(iso)}
              aria-pressed={selected}
              onClick={() => onPick(iso)}
              className={cn(
                "tabular mx-auto size-8 rounded-sm text-sm hover:bg-surface-3 disabled:pointer-events-none disabled:text-text-3 disabled:opacity-40",
                iso === today && !selected && "font-semibold text-primary",
                selected && "bg-primary text-text-inverse hover:bg-primary-hover",
              )}
            >
              {Number(iso.slice(8, 10))}
            </button>
          );
        })}
      </div>
    </div>
  );
}

type DatePickerProps = {
  id?: string;
  value: string;
  onChange: (iso: string) => void;
  onInvalid?: (invalid: boolean) => void;
  min?: string;
  max?: string;
  disabled?: boolean;
  "aria-describedby"?: string;
  "aria-invalid"?: true | undefined;
};

/** Accepts `12 Oct 2026` and `12/10/2026` typed in, or a pick from the calendar. */
export function DatePicker({
  value,
  onChange,
  onInvalid,
  min,
  max,
  disabled,
  ...aria
}: DatePickerProps) {
  const [text, setText] = useState(formatDate(value));
  const [open, setOpen] = useState(false);
  useEffect(() => setText(formatDate(value)), [value]);
  const commit = () => {
    const trimmed = text.trim();
    if (!trimmed) {
      onChange("");
      onInvalid?.(false);
      return;
    }
    const parsed = parseTypedDate(trimmed);
    if (parsed) {
      onChange(parsed);
      setText(formatDate(parsed));
      onInvalid?.(false);
    } else {
      onInvalid?.(true);
    }
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div className="relative">
        <Input
          {...aria}
          value={text}
          disabled={disabled}
          placeholder={common.date.hint}
          onChange={(event) => setText(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
          }}
          className="pr-10"
        />
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={common.date.openCalendar}
            className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-sm text-text-3 hover:text-text"
          >
            <CalendarDays size={16} strokeWidth={1.5} />
          </button>
        </PopoverTrigger>
      </div>
      <PopoverContent>
        <Calendar
          value={value}
          min={min}
          max={max}
          onPick={(iso) => {
            onChange(iso);
            onInvalid?.(false);
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

export function DateField({
  label,
  value,
  onChange,
  error,
  hint,
  optional,
  min,
  max,
  disabled,
  className,
}: {
  label: string;
  value: string;
  onChange: (iso: string) => void;
  error?: string | undefined;
  hint?: string;
  optional?: boolean;
  min?: string;
  max?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [invalid, setInvalid] = useState(false);
  return (
    <Field
      label={label}
      error={invalid ? common.date.invalid : error}
      hint={hint}
      optional={optional}
      className={className}
    >
      {(ids) => (
        <DatePicker
          {...ids}
          value={value}
          onChange={onChange}
          onInvalid={setInvalid}
          min={min}
          max={max}
          disabled={disabled}
        />
      )}
    </Field>
  );
}

export { addDays };

// ------------------------------------------------------------------ combobox

/** A searchable list. The parent supplies the options for the current query. */
export function Combobox<T>({
  id,
  value,
  onChange,
  options,
  loading,
  onQueryChange,
  itemKey,
  itemLabel,
  itemMeta,
  placeholder,
  searchPlaceholder,
  disabled,
  ...aria
}: {
  id?: string;
  value: T | null;
  onChange: (value: T) => void;
  options: T[];
  loading?: boolean;
  onQueryChange: (query: string) => void;
  itemKey: (item: T) => string;
  itemLabel: (item: T) => string;
  itemMeta?: (item: T) => ReactNode;
  placeholder: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  "aria-describedby"?: string;
  "aria-invalid"?: true | undefined;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) onQueryChange("");
      }}
    >
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(controlClass, "flex items-center justify-between gap-2 text-left")}
          {...aria}
        >
          <span className={cn("truncate", !value && "text-text-3")}>
            {value ? itemLabel(value) : placeholder}
          </span>
          <ChevronsUpDown size={14} strokeWidth={1.5} className="shrink-0 text-text-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] min-w-64 p-0">
        <Command shouldFilter={false}>
          <Command.Input
            placeholder={searchPlaceholder ?? common.combobox.typeToSearch}
            onValueChange={onQueryChange}
            className="h-9 w-full border-b border-border bg-transparent px-3 text-base outline-none placeholder:text-text-3"
          />
          <Command.List className="max-h-64 overflow-y-auto p-1">
            <Command.Empty className="px-3 py-2 text-sm text-text-3">
              {loading ? common.combobox.searching : common.combobox.empty}
            </Command.Empty>
            {options.map((item) => (
              <Command.Item
                key={itemKey(item)}
                value={itemKey(item)}
                onSelect={() => {
                  onChange(item);
                  setOpen(false);
                }}
                className="flex min-h-8 cursor-pointer items-center justify-between gap-3 rounded-sm px-2 py-1 text-base data-[selected=true]:bg-surface-2"
              >
                <span className="truncate">{itemLabel(item)}</span>
                {itemMeta ? (
                  <span className="shrink-0 text-xs text-text-3">{itemMeta(item)}</span>
                ) : null}
              </Command.Item>
            ))}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// ------------------------------------------------------------------ pack stepper

/** Steps an order quantity by whole packs and shows what that comes to. */
export function PackStepper({
  value,
  packSize,
  onChange,
  unitLabel = common.units.units,
  packLabel = common.units.packs,
  ariaLabel,
}: {
  value: number;
  packSize: number;
  onChange: (units: number) => void;
  unitLabel?: string;
  packLabel?: string;
  ariaLabel: string;
}) {
  const size = packSize > 0 ? packSize : 1;
  const packs = value / size;
  return (
    <div className="inline-flex flex-col gap-1">
      <div className="inline-flex items-center gap-1">
        <Button
          size="sm"
          aria-label={common.stepper.decrease}
          disabled={value <= 0}
          onClick={() => onChange(Math.max(0, value - size))}
          className="w-8 px-0"
        >
          -
        </Button>
        <NumberInput
          aria-label={ariaLabel}
          value={String(value)}
          decimals={false}
          suffix={unitLabel}
          onChange={(event) => {
            const next = Number(event.target.value.replace(/[^0-9]/g, ""));
            onChange(Number.isFinite(next) ? next : 0);
          }}
          className="h-8 w-28"
        />
        <Button
          size="sm"
          aria-label={common.stepper.increase}
          onClick={() => onChange(value + size)}
          className="w-8 px-0"
        >
          +
        </Button>
      </div>
      <span className="tabular text-xs text-text-3">
        {common.stepper.total(
          String(value),
          `${Number.isInteger(packs) ? packs : packs.toFixed(1)} ${packLabel}`,
        )}
      </span>
    </div>
  );
}

// ------------------------------------------------------------------ toast

export function ToastHost() {
  return (
    <Toaster
      position="bottom-right"
      duration={4000}
      closeButton
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "flex w-80 items-start gap-3 rounded-md border border-border-strong bg-surface p-3 text-base text-text shadow-popover",
          error: "border-critical",
          closeButton: "ml-auto text-text-3 hover:text-text",
          title: "text-base",
          description: "text-sm text-text-2",
        },
      }}
    />
  );
}

export const notify = {
  success: (message: string) => toast(message),
  error: (message: string, description?: string) =>
    toast(message, { duration: Infinity, description, className: "border-critical" }),
};

// ------------------------------------------------------------------ command palette

export type PaletteItem = { id: string; label: string; meta?: string; onSelect: () => void };

export function CommandPalette({
  open,
  onOpenChange,
  pages,
  products,
  onQueryChange,
  searching,
  copy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pages: PaletteItem[];
  products: PaletteItem[];
  onQueryChange: (query: string) => void;
  searching?: boolean;
  copy: typeof common.commandPalette;
}) {
  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label={copy.title}
      shouldFilter={false}
      overlayClassName="fade-in fixed inset-0 z-40 bg-text/30"
      contentClassName="dialog-in fixed top-1/2 left-1/2 z-50 w-[calc(100vw-32px)] max-w-[560px] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-lg border border-border bg-surface shadow-dialog"
    >
      <Command.Input
        placeholder={copy.placeholder}
        onValueChange={onQueryChange}
        className="h-12 w-full border-b border-border bg-transparent px-4 text-md outline-none placeholder:text-text-3"
      />
      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="px-3 py-3 text-sm text-text-3">
          {searching ? copy.searching : copy.empty}
        </Command.Empty>
        {pages.length > 0 ? (
          <Command.Group
            heading={copy.pages}
            className="text-xs text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
          >
            {pages.map((item) => (
              <PaletteRow key={item.id} item={item} onDone={() => onOpenChange(false)} />
            ))}
          </Command.Group>
        ) : null}
        {products.length > 0 ? (
          <Command.Group
            heading={copy.products}
            className="text-xs text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
          >
            {products.map((item) => (
              <PaletteRow key={item.id} item={item} onDone={() => onOpenChange(false)} />
            ))}
          </Command.Group>
        ) : null}
      </Command.List>
    </Command.Dialog>
  );
}

function PaletteRow({ item, onDone }: { item: PaletteItem; onDone: () => void }) {
  return (
    <Command.Item
      value={item.id}
      onSelect={() => {
        item.onSelect();
        onDone();
      }}
      className="flex min-h-9 cursor-pointer items-center justify-between gap-3 rounded-sm px-2 text-base text-text data-[selected=true]:bg-surface-2"
    >
      <span className="truncate">{item.label}</span>
      {item.meta ? <span className="font-mono text-xs text-text-3">{item.meta}</span> : null}
    </Command.Item>
  );
}
