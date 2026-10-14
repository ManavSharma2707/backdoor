import { useState } from "react";
import { useApiQuery } from "@/lib/queries";
import { useDebounced } from "@/lib/hooks";
import { quantity } from "@/lib/format";
import { common } from "@/copy/common";
import type { Page, Product } from "@/types/models";
import { Combobox } from "@/components/ui/pickers";

/** Pick one product by name, SKU or barcode. */
export function ProductPicker({
  value,
  onChange,
  placeholder,
  ...aria
}: {
  value: Product | null;
  onChange: (product: Product) => void;
  placeholder: string;
  id?: string;
  disabled?: boolean;
  "aria-describedby"?: string;
  "aria-invalid"?: true | undefined;
}) {
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, 200);
  const results = useApiQuery<Page<Product>>("/products", { q: debounced, page_size: 12 });
  return (
    <Combobox
      {...aria}
      value={value}
      onChange={onChange}
      options={results.data?.items ?? []}
      loading={results.isFetching}
      onQueryChange={setQuery}
      itemKey={(p) => p.id}
      itemLabel={(p) => p.name}
      itemMeta={(p) => `${p.sku}, ${quantity(p.on_hand)} ${common.units.units}`}
      placeholder={placeholder}
    />
  );
}
