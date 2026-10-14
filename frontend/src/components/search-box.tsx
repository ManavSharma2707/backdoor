import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useDebounced } from "@/lib/hooks";
import { Input } from "@/components/ui/field";

/** Search field that writes to the address after a short pause. `/` focuses it. */
export function SearchBox({
  value,
  onChange,
  label,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder: string;
}) {
  const [text, setText] = useState(value);
  const debounced = useDebounced(text, 300);
  const last = useRef(value);

  useEffect(() => {
    if (value !== last.current) {
      last.current = value;
      setText(value);
    }
  }, [value]);

  useEffect(() => {
    if (debounced !== last.current) {
      last.current = debounced;
      onChange(debounced);
    }
  }, [debounced, onChange]);

  return (
    <div className="relative w-full sm:w-72">
      <Search
        size={14}
        strokeWidth={1.5}
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
      />
      <Input
        type="search"
        data-screen-search
        aria-label={label}
        placeholder={placeholder}
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="pl-9"
      />
    </div>
  );
}
