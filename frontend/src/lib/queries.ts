import { keepPreviousData, useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { get, type Query } from "@/lib/api";
import type { Category, Page, Settings, Supplier } from "@/types/models";

/** A GET that lives in the query cache under its path and params. */
export function useApiQuery<T>(
  path: string,
  query?: Query,
  options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">,
) {
  return useQuery<T>({
    queryKey: [path, query ?? {}],
    queryFn: ({ signal }) => get<T>(path, query, signal),
    ...options,
  });
}

/** A paged list where the previous page stays on screen while the next one loads. */
export function useListQuery<T>(path: string, query: Query) {
  return useQuery<Page<T>>({
    queryKey: [path, query],
    queryFn: ({ signal }) => get<Page<T>>(path, query, signal),
    placeholderData: keepPreviousData,
  });
}

export const useSettings = () =>
  useApiQuery<Settings>("/settings", undefined, { staleTime: 5 * 60_000 });

export const useCategories = () =>
  useApiQuery<Category[]>("/categories", undefined, { staleTime: 5 * 60_000 });

export const useSuppliers = () =>
  useApiQuery<Page<Supplier>>(
    "/suppliers",
    { page_size: 200, active: true },
    { staleTime: 5 * 60_000 },
  );
