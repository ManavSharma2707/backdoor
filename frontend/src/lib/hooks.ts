import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";

export function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/**
 * Filters, sort, page and tab live in the query string so views can be linked.
 * Values equal to their default are left out of the address.
 */
export function useQueryParams<T extends Record<string, string>>(defaults: T) {
  const [search, setSearch] = useSearchParams();
  const values = useMemo(() => {
    const out: Record<string, string> = { ...defaults };
    for (const key of Object.keys(defaults)) {
      const found = search.get(key);
      if (found !== null) out[key] = found;
    }
    return out as T;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const set = useCallback(
    (patch: Partial<Record<keyof T, string | null>>, options: { keepPage?: boolean } = {}) => {
      setSearch(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(patch)) {
            if (value === null || value === undefined || value === defaults[key]) next.delete(key);
            else next.set(key, value as string);
          }
          if (!options.keepPage && !("page" in patch)) next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setSearch],
  );
  return [values, set] as const;
}

/** Focuses the element marked `data-screen-search` when `/` is pressed outside a field. */
export function useSlashToSearch() {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (target?.isContentEditable) return;
      const field = document.querySelector<HTMLElement>("[data-screen-search]");
      if (field) {
        event.preventDefault();
        field.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** A key that stays the same until reset. Used for idempotency keys on forms. */
export function newKey(): string {
  return crypto.randomUUID();
}
