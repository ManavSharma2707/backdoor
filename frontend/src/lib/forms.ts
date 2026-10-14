import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { isApiError } from "@/lib/api";
import { common } from "@/copy/common";

/** A positive or zero amount typed as text, up to `places` decimals. */
export const decimalPattern = (places: number) => new RegExp(`^\\d+(\\.\\d{1,${places}})?$`);

export const isDecimal = (value: string, places = 4) => decimalPattern(places).test(value.trim());

export const toNumber = (value: string): number => Number(value.trim().replace(/,/g, ""));

/**
 * Puts the server's field messages on the matching form fields.
 * Returns the message to show for the form as a whole when no field matched.
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly string[],
): string | null {
  if (!isApiError(error)) return common.errors.server;
  if (error.code === "NETWORK") return common.errors.network;
  let matched = false;
  for (const detail of error.details) {
    const name = detail.field.replace(/^(body|query)\./, "");
    if (fields.includes(name)) {
      setError(name as Path<T>, { type: "server", message: detail.issue });
      matched = true;
    }
  }
  return matched ? null : error.message;
}

export function errorText(error: unknown): string {
  if (isApiError(error)) return error.code === "NETWORK" ? common.errors.network : error.message;
  return common.errors.server;
}
