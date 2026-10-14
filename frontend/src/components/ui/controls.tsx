import { useId, type ReactNode } from "react";
import { Checkbox as C, RadioGroup as R, Switch as S, Tabs as T } from "radix-ui";
import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

// ------------------------------------------------------------------ tabs (underline)

export type TabItem = { value: string; label: string; count?: number | string };

export function Tabs({
  value,
  onValueChange,
  items,
  children,
  label,
}: {
  value: string;
  onValueChange: (value: string) => void;
  items: TabItem[];
  children?: ReactNode;
  label: string;
}) {
  return (
    <T.Root value={value} onValueChange={onValueChange}>
      <T.List aria-label={label} className="mb-4 flex gap-6 overflow-x-auto border-b border-border">
        {items.map((item) => (
          <T.Trigger
            key={item.value}
            value={item.value}
            className={cn(
              "-mb-px h-10 shrink-0 border-b-2 border-transparent text-base font-medium whitespace-nowrap text-text-2",
              "hover:text-text data-[state=active]:border-primary data-[state=active]:text-text",
            )}
          >
            {item.label}
            {item.count !== undefined ? (
              <span className="ml-1.5 font-normal text-text-3">({item.count})</span>
            ) : null}
          </T.Trigger>
        ))}
      </T.List>
      {children}
    </T.Root>
  );
}

export const TabPanel = T.Content;

// ------------------------------------------------------------------ checkbox, switch, segmented

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
  labelHidden,
}: {
  checked: boolean | "indeterminate";
  onCheckedChange: (checked: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
  labelHidden?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-2">
      <C.Root
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(next) => onCheckedChange(next === true)}
        className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-sm border border-border-strong bg-surface data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=indeterminate]:border-primary data-[state=indeterminate]:bg-primary disabled:opacity-50"
      >
        <C.Indicator className="text-text-inverse">
          {checked === "indeterminate" ? (
            <span className="block h-0.5 w-2 bg-text-inverse" />
          ) : (
            <Check size={12} strokeWidth={2.5} />
          )}
        </C.Indicator>
      </C.Root>
      <label htmlFor={id} className={cn("text-base", labelHidden && "sr-only")}>
        {label}
        {hint ? <span className="block text-xs text-text-3">{hint}</span> : null}
      </label>
    </div>
  );
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <S.Root
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
        className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-border-strong transition-colors data-[state=checked]:bg-primary disabled:opacity-50"
      >
        <S.Thumb className="block size-4 translate-x-0.5 rounded-full bg-surface transition-transform duration-150 data-[state=checked]:translate-x-[18px]" />
      </S.Root>
      <label htmlFor={id} className="text-base">
        {label}
        {hint ? <span className="block text-xs text-text-3">{hint}</span> : null}
      </label>
    </div>
  );
}

export type SegmentOption<V extends string> = { value: V; label: string };

/** A short list of exclusive choices shown side by side, for example the payment mode. */
export function Segmented<V extends string>({
  value,
  onValueChange,
  options,
  label,
  className,
}: {
  value: V;
  onValueChange: (value: V) => void;
  options: SegmentOption<V>[];
  label: string;
  className?: string;
}) {
  return (
    <R.Root
      value={value}
      onValueChange={(v) => onValueChange(v as V)}
      aria-label={label}
      className={cn(
        "inline-flex rounded-sm border border-border-strong bg-surface p-0.5",
        className,
      )}
    >
      {options.map((option) => (
        <R.Item
          key={option.value}
          value={option.value}
          className="h-8 flex-1 whitespace-nowrap rounded-sm px-3 text-base text-text-2 hover:text-text data-[state=checked]:bg-primary-soft data-[state=checked]:font-medium data-[state=checked]:text-primary pointer-coarse:h-9"
        >
          {option.label}
        </R.Item>
      ))}
    </R.Root>
  );
}
