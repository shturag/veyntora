"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { GroupOption } from "./source-forms";

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";

/** Rows of "entra:<id>" / "site:<name>" (or a Confluence group, a SID) -> Veyntora group. */
export function GroupMap({
  groups,
  value,
  legend,
  hint,
  placeholder = "entra:… / site:…",
}: {
  groups: GroupOption[];
  value: Record<string, string>;
  legend?: string;
  hint?: string;
  placeholder?: string;
}) {
  const t = useTranslations("sources");
  const [rows, setRows] = useState(
    Object.entries(value).length ? Object.entries(value) : [["", ""]],
  );
  return (
    <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
      <legend className="mb-1 text-[13px] font-medium">{legend ?? t("groupMap")}</legend>
      <p className="m-0 text-xs text-fg-muted">{hint ?? t("groupMapHint")}</p>
      {rows.map(([key, group], i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr] gap-2 max-[640px]:grid-cols-1">
          <input
            name="map_key"
            aria-label={t("mapKey")}
            defaultValue={key}
            placeholder={placeholder}
            className={`${input} font-mono`}
          />
          <select
            name="map_group"
            aria-label={t("mapGroup")}
            defaultValue={group}
            className={input}
          >
            <option value="">{t("chooseGroup")}</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
      ))}
      <div>
        <Button type="button" size="sm" onClick={() => setRows([...rows, ["", ""]])}>
          {t("addMapping")}
        </Button>
      </div>
    </fieldset>
  );
}

export function mapFrom(form: FormData): Record<string, string> {
  const keys = form.getAll("map_key").map(String);
  const groups = form.getAll("map_group").map(String);
  const out: Record<string, string> = {};
  keys.forEach((k, i) => {
    if (k.trim() && groups[i]) out[k.trim()] = groups[i]!;
  });
  return out;
}
