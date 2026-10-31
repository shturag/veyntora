"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Tool = components["schemas"]["ToolOut"];
type Group = components["schemas"]["ToolGroupOption"];

const control = "h-9 rounded-md border border-line-strong bg-surface px-2 text-sm";

/** Review one tool: its description as the agent sees it, class, approval, callers, limit. */
export function ToolRow({
  tool,
  groups,
  canEdit,
  serverActive,
}: {
  tool: Tool;
  groups: Group[];
  canEdit: boolean;
  serverActive: boolean;
}) {
  const t = useTranslations("tools");
  const router = useRouter();
  const [access, setAccess] = useState(tool.access);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const read = access === "read";
  const destructive = access === "destructive";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const enabled = f.get("enabled") === "on";
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/tools/${tool.id}`, {
        method: "PATCH",
        headers: { "If-Match": String(tool.version) },
        body: JSON.stringify({
          access,
          enabled,
          acknowledge_flag: f.get("acknowledge") === "on",
          requires_approval: read ? f.get("approval") === "needed" : true,
          approver_group_id: read ? null : String(f.get("approver") || "") || null,
          caller_group_ids: f.getAll("callers").map(String),
          rate_limit_per_minute: Number(f.get("rate") || 0) || null,
        }),
      });
      setMessage({ ok: true, text: t("saved") });
      router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;
  return (
    <li className="rounded-lg border border-line bg-surface p-4">
      <form aria-label={tool.name} onSubmit={save} className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <span className="font-mono text-sm font-semibold">{tool.name}</span>
            <p className="m-0 text-sm whitespace-pre-wrap text-fg-secondary">
              {tool.description || t("noDescription")}
            </p>
            {tool.flagged ? (
              <p role="note" className="m-0 rounded-md bg-amber-soft px-2 py-1 text-xs text-amber">
                {t("flagged", { reason: tool.flagged })}
              </p>
            ) : null}
            {!tool.present ? <Badge tone="neutral">{t("gone")}</Badge> : null}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="enabled"
              defaultChecked={tool.enabled}
              disabled={
                disabled || destructive || !tool.present || (!serverActive && !tool.enabled)
              }
              className="size-4"
            />
            {t("enabled")}
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("classify")}
            <select
              value={access}
              onChange={(e) => setAccess(e.target.value as Tool["access"])}
              disabled={disabled}
              className={control}
            >
              {(["read", "write", "destructive"] as const).map((a) => (
                <option key={a} value={a}>
                  {t(`access.${a}`)}
                </option>
              ))}
            </select>
          </label>
          {read ? (
            <label className="flex flex-col gap-1 text-[13px] font-medium">
              {t("approvalLabel")}
              <select
                name="approval"
                defaultValue={tool.requires_approval ? "needed" : "not_needed"}
                disabled={disabled}
                className={control}
              >
                <option value="not_needed">{t("approvalNotNeeded")}</option>
                <option value="needed">{t("approvalNeeded")}</option>
              </select>
            </label>
          ) : destructive ? (
            <span className="pb-2 text-sm text-red">{t("blocked")}</span>
          ) : (
            <label className="flex flex-col gap-1 text-[13px] font-medium">
              {t("approvers")}
              <select
                name="approver"
                defaultValue={tool.approver_group_id ?? ""}
                disabled={disabled}
                className={control}
              >
                <option value="">{t("platformAdmins")}</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("callers")}
            <select
              name="callers"
              multiple
              defaultValue={tool.caller_group_ids}
              disabled={disabled || destructive}
              className="min-h-9 rounded-md border border-line-strong bg-surface px-2 text-sm"
              size={Math.min(4, Math.max(2, groups.length))}
            >
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-fg-muted">{t("callersHint")}</span>
          </label>
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("rateLimit")}
            <input
              name="rate"
              type="number"
              min={1}
              max={10000}
              defaultValue={tool.rate_limit_per_minute ?? ""}
              disabled={disabled || destructive}
              className={`${control} w-28`}
            />
          </label>
        </div>
        {canEdit ? (
          <div className="flex flex-wrap items-center gap-3">
            {tool.flagged && !tool.enabled ? (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name="acknowledge" className="size-4" />
                {t("acknowledge")}
              </label>
            ) : null}
            <Button type="submit" size="sm" disabled={busy}>
              {t("save")}
            </Button>
            {message ? (
              <span
                role={message.ok ? "status" : "alert"}
                className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
              >
                {message.text}
              </span>
            ) : null}
          </div>
        ) : null}
      </form>
    </li>
  );
}
