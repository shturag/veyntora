"use client";

import { control, field, FormDialog, useAction } from "../evaluation/evaluation-actions";

/** "Export audit log": range, format, masking; the browser downloads the file. */
export function ExportAudit() {
  const state = useAction("audit");
  const { t } = state;
  return (
    <FormDialog
      label={t("export")}
      title={t("exportTitle")}
      submit={t("exportStart")}
      state={state}
      onSubmit={(f) => {
        const q = new URLSearchParams({
          range: String(f.get("range")),
          format: String(f.get("format")),
          mask: String(f.get("mask") === "on"),
        });
        const link = document.createElement("a");
        link.href = `/api/v1/admin/audit/export?${q}`;
        link.download = "";
        link.click();
        state.setMessage({ ok: true, text: t("exportReady") });
      }}
    >
      <label className={field}>
        {t("range")}
        <select name="range" defaultValue="30d" className={control}>
          {(["7d", "30d", "90d", "all"] as const).map((r) => (
            <option key={r} value={r}>
              {t(`ranges.${r}`)}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        {t("format")}
        <select name="format" defaultValue="csv" className={control}>
          <option value="csv">CSV</option>
          <option value="jsonl">{t("jsonl")}</option>
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="mask" defaultChecked className="size-4" />
        {t("maskExport")}
      </label>
      <p className="m-0 text-xs text-fg-muted">{t("exportNote")}</p>
    </FormDialog>
  );
}
