"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Row = components["schemas"]["PersonRow"];

/** Find a person by name or e-mail (Users & groups search). */
export function PersonPicker({
  label,
  value,
  onChange,
  exclude,
}: {
  label: string;
  value: { id: string; name: string } | null;
  onChange: (person: { id: string; name: string } | null) => void;
  exclude?: string;
}) {
  const t = useTranslations("people");
  const id = useId();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Row[]>([]);

  const searching = q.trim().length >= 2;
  useEffect(() => {
    if (!searching) return;
    const timer = window.setTimeout(() => {
      void api<Row[]>(`/v1/admin/people?q=${encodeURIComponent(q.trim())}&limit=8`)
        .then((found) => setRows(found.filter((r) => r.id !== exclude)))
        .catch(() => setRows([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, exclude, searching]);
  const shown = searching ? rows : [];

  return (
    <div className="flex flex-col gap-1 text-[13px] font-medium">
      <label htmlFor={id}>{label}</label>
      {value ? (
        <span className="flex h-10 items-center gap-2 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal">
          {value.name}
          <button
            type="button"
            className="text-fg-muted"
            aria-label={t("clear")}
            onClick={() => onChange(null)}
          >
            ×
          </button>
        </span>
      ) : (
        <div className="relative">
          <input
            id={id}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("searchPerson")}
            className="h-10 w-56 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal"
          />
          {shown.length ? (
            <ul className="absolute z-10 m-0 mt-1 flex w-full list-none flex-col rounded-md border border-line bg-surface p-1 shadow-popover">
              {shown.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    className="w-full rounded px-2 py-1.5 text-left text-sm font-normal hover:bg-sunken"
                    onClick={() => {
                      onChange({ id: r.id, name: r.name });
                      setQ("");
                    }}
                  >
                    {r.name} <span className="text-xs text-fg-muted">{r.email}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </div>
  );
}
