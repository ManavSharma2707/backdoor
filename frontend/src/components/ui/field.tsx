import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type Ref,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";
import { common } from "@/copy/common";

export const controlClass = cn(
  "h-9 w-full rounded-sm border border-border-strong bg-surface px-3 text-base text-text",
  "placeholder:text-text-3 disabled:bg-surface-2 disabled:text-text-3",
  "aria-[invalid=true]:border-critical pointer-coarse:h-10",
);

type FieldIds = {
  id: string;
  "aria-describedby": string | undefined;
  "aria-invalid": true | undefined;
};

type FieldProps = {
  label: string;
  hint?: ReactNode;
  error?: string | undefined;
  optional?: boolean;
  className?: string;
  labelHidden?: boolean;
  children: (ids: FieldIds) => ReactNode;
};

/** Label above, helper text below, error text in critical. Optional fields say "Optional". */
export function Field({
  label,
  hint,
  error,
  optional,
  className,
  labelHidden,
  children,
}: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ");
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label
        htmlFor={id}
        className={cn("flex items-baseline gap-2 text-sm font-medium", labelHidden && "sr-only")}
      >
        {label}
        {optional ? (
          <span className="text-xs font-normal text-text-3">{common.optional}</span>
        ) : null}
      </label>
      {children({
        id,
        "aria-describedby": describedBy || undefined,
        "aria-invalid": error ? true : undefined,
      })}
      {error ? (
        <p id={errorId} className="text-xs text-critical">
          {error}
        </p>
      ) : null}
      {hint ? (
        <p id={hintId} className="text-xs text-text-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type FieldWrapProps = Omit<FieldProps, "children">;

type InputBase = Omit<InputHTMLAttributes<HTMLInputElement>, "size"> & {
  ref?: Ref<HTMLInputElement>;
};

export function Input({ className, ref, ...rest }: InputBase) {
  return <input ref={ref} className={cn(controlClass, className)} {...rest} />;
}

export function TextField({
  label,
  hint,
  error,
  optional,
  labelHidden,
  wrapperClassName,
  ...input
}: InputBase & FieldWrapProps & { wrapperClassName?: string }) {
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      optional={optional}
      labelHidden={labelHidden}
      className={wrapperClassName}
    >
      {(ids) => <Input {...ids} {...input} />}
    </Field>
  );
}

type NumberInputProps = InputBase & { suffix?: string; decimals?: boolean };

/** Right aligned, tabular, with the unit inside the field. Holds text, so zod does the checking. */
export function NumberInput({
  suffix,
  decimals = true,
  className,
  ref,
  ...rest
}: NumberInputProps) {
  return (
    <div className="relative">
      <input
        ref={ref}
        type="text"
        inputMode={decimals ? "decimal" : "numeric"}
        autoComplete="off"
        className={cn(controlClass, "tabular text-right", suffix && "pr-14", className)}
        {...rest}
      />
      {suffix ? (
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-text-3">
          {suffix}
        </span>
      ) : null}
    </div>
  );
}

export function NumberField({
  label,
  hint,
  error,
  optional,
  labelHidden,
  wrapperClassName,
  ...input
}: NumberInputProps & FieldWrapProps & { wrapperClassName?: string }) {
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      optional={optional}
      labelHidden={labelHidden}
      className={wrapperClassName}
    >
      {(ids) => <NumberInput {...ids} {...input} />}
    </Field>
  );
}

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  ref?: Ref<HTMLTextAreaElement>;
};

export function TextareaField({
  label,
  hint,
  error,
  optional,
  wrapperClassName,
  className,
  ...rest
}: TextareaProps & FieldWrapProps & { wrapperClassName?: string }) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional} className={wrapperClassName}>
      {(ids) => (
        <textarea
          rows={3}
          className={cn(controlClass, "h-auto min-h-16 py-2", className)}
          {...ids}
          {...rest}
        />
      )}
    </Field>
  );
}

type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> & {
  ref?: Ref<HTMLSelectElement>;
};

/** A native select: reliable on phones, fully keyboard accessible, no extra weight. */
export function Select({ className, children, ref, ...rest }: SelectProps) {
  return (
    <div className="relative">
      <select ref={ref} className={cn(controlClass, "appearance-none pr-8", className)} {...rest}>
        {children}
      </select>
      <svg
        className="pointer-events-none absolute top-1/2 right-3 size-3 -translate-y-1/2 text-text-3"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden="true"
      >
        <path d="M2 4.5 6 8.5l4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}

export function SelectField({
  label,
  hint,
  error,
  optional,
  labelHidden,
  wrapperClassName,
  children,
  ...select
}: SelectProps & FieldWrapProps & { wrapperClassName?: string }) {
  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      optional={optional}
      labelHidden={labelHidden}
      className={wrapperClassName}
    >
      {(ids) => (
        <Select {...ids} {...select}>
          {children}
        </Select>
      )}
    </Field>
  );
}
