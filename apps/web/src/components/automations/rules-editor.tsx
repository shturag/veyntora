"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";

import { control, type Rule } from "./spec";

const OPS = ["equals", "not_equals", "contains", "gt", "lt", "is_one_of", "within_days"] as const;

/** Rows of "field · operator · value" (conditions, watcher rules, event filters). */
export function RulesEditor({
  rules,
  onChange,
  fields,
  label,
  min = 0,
}: {
  rules: Rule[];
  onChange: (rules: Rule[]) => void;
  fields: string[];
  label: string;
  min?: number;
}) {
  const t = useTranslations("automations");
  const set = (i: number, patch: Partial<Rule>) =>
    onChange(rules.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const listId = `fields-${label.replace(/\W+/g, "-")}`;
  return (
    <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
      <legend className="mb-1 text-[13px] font-medium">{label}</legend>
      <datalist id={listId}>
        {fields.map((f) => (
          <option key={f} value={f.replace(/[{}]/g, "")} />
        ))}
      </datalist>
      {rules.map((r, i) => (
        <div key={i} className="grid grid-cols-[1.3fr_1fr_1fr_auto] gap-2 max-[640px]:grid-cols-1">
          <input
            aria-label={t("ruleField", { n: i + 1 })}
            list={listId}
            value={r.field}
            onChange={(e) => set(i, { field: e.target.value })}
            className={`${control} font-mono`}
            placeholder="event.amount"
          />
          <select
            aria-label={t("ruleOp", { n: i + 1 })}
            value={r.op}
            onChange={(e) => set(i, { op: e.target.value as Rule["op"] })}
            className={control}
          >
            {OPS.map((op) => (
              <option key={op} value={op}>
                {t(`ops.${op}`)}
              </option>
            ))}
          </select>
          <input
            aria-label={t("ruleValue", { n: i + 1 })}
            value={r.value}
            onChange={(e) => set(i, { value: e.target.value })}
            className={control}
          />
          <Button
            type="button"
            aria-label={t("removeRule", { n: i + 1 })}
            disabled={rules.length <= min}
            onClick={() => onChange(rules.filter((_, n) => n !== i))}
          >
            ×
          </Button>
        </div>
      ))}
      <div>
        <Button
          type="button"
          size="sm"
          onClick={() => onChange([...rules, { field: "event.key", op: "equals", value: "" }])}
        >
          {t("addCondition")}
        </Button>
      </div>
    </fieldset>
  );
}
