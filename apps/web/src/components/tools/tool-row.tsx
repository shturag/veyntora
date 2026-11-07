"use client";

import { Badge, Button, cn } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Tool = components["schemas"]["ToolOut"];
type Group = components["schemas"]["ToolGroupOption"];

const control =
  "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm disabled:bg-sunken disabled:text-fg-muted";
const field = "flex flex-col gap-1.5 text-[13px] font-medium";
const ACCESS_TONE = { read: "info", write: "amber", destructive: "red" } as const;

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
  const [enabled, setEnabled] = useState(tool.enabled);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const read = access === "read";
  const destructive = access === "destructive";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/tools/${tool.id}`, {
        method: "PATCH",
        headers: { "If-Match": String(tool.version) },
        body: JSON.stringify({
          access,
          enabled: enabled && !destructive,
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
  const canEnable = !destructive && tool.present && (serverActive || tool.enabled);
  const switchHint = destructive
    ? t("blockedHint")
    : !canEnable
      ? t("enableAfterSignOff")
      : enabled
        ? t("enabledHint")
        : t("offHint");
  return (
    <li className="border-t border-line first:border-t-0">
      <form aria-label={tool.name} onSubmit={save} className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="m-0 font-mono text-[15px] font-semibold">{tool.name}</h3>
          <Badge tone={ACCESS_TONE[tool.access]}>{t(`access.${tool.access}`)}</Badge>
          <Badge tone={tool.enabled ? "green" : "neutral"}>
            {tool.enabled ? t("on") : t("offBadge")}
          </Badge>
          {!tool.present ? <Badge tone="neutral">{t("gone")}</Badge> : null}
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold tracking-wide text-fg-muted uppercase">
            {t("agentSees")}
          </span>
          <p className="m-0 rounded-md border border-line bg-sunken px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap text-fg-secondary">
            {tool.description || t("noDescription")}
          </p>
          {tool.flagged ? (
            <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t("flagged", { reason: tool.flagged })}
            </p>
          ) : null}
        </div>

        <fieldset className="m-0 grid grid-cols-3 gap-4 border-0 p-0 max-[900px]:grid-cols-1">
          <legend className="sr-only">{t("policy")}</legend>
          <label className={field}>
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
            <label className={field}>
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
            <div className={field}>
              {t("approvalLabel")}
              <span className="flex h-10 items-center text-sm font-normal text-red">
                {t("blocked")}
              </span>
            </div>
          ) : (
            <label className={field}>
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
          <label className={field}>
            {t("rateLimit")}
            <input
              name="rate"
              type="number"
              min={1}
              max={10000}
              placeholder={t("noLimit")}
              defaultValue={tool.rate_limit_per_minute ?? ""}
              disabled={disabled || destructive}
              className={control}
            />
          </label>
          <fieldset className="col-span-full m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1.5 p-0 text-[13px] font-medium">{t("callers")}</legend>
            <div className="flex flex-wrap gap-2">
              {groups.map((g) => (
                <label
                  key={g.id}
                  className={cn(
                    "inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border border-line-strong bg-surface px-3 text-sm",
                    "has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-accent",
                    "has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60",
                    "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                  )}
                >
                  <input
                    type="checkbox"
                    name="callers"
                    value={g.id}
                    defaultChecked={tool.caller_group_ids.includes(g.id)}
                    disabled={disabled || destructive}
                    className="size-4 accent-[var(--color-accent)]"
                  />
                  {g.name}
                </label>
              ))}
            </div>
            <span className="text-xs text-fg-muted">{t("callersHint")}</span>
          </fieldset>
        </fieldset>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <label
            className={cn(
              "flex items-center gap-3",
              disabled || !canEnable ? "cursor-not-allowed" : "cursor-pointer",
            )}
          >
            <input
              type="checkbox"
              role="switch"
              checked={enabled && !destructive}
              onChange={(e) => setEnabled(e.target.checked)}
              disabled={disabled || (!canEnable && !enabled)}
              className="peer sr-only"
            />
            <span
              aria-hidden
              className={cn(
                "inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors",
                "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent peer-disabled:opacity-50",
                enabled && !destructive ? "bg-accent" : "bg-line-strong",
              )}
            >
              <span
                className={cn(
                  "size-4 rounded-full bg-surface shadow-sm transition-transform",
                  enabled && !destructive ? "translate-x-4" : "",
                )}
              />
            </span>
            <span className="flex flex-col">
              <span className="text-sm font-medium">{t("enabled")}</span>
              <span className="text-xs text-fg-muted">{switchHint}</span>
            </span>
          </label>
          {canEdit ? (
            <div className="flex flex-wrap items-center gap-3">
              {message ? (
                <span
                  role={message.ok ? "status" : "alert"}
                  className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
                >
                  {message.text}
                </span>
              ) : null}
              {tool.flagged && !tool.enabled ? (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" name="acknowledge" className="size-4" />
                  {t("acknowledge")}
                </label>
              ) : null}
              <Button type="submit" variant="primary" size="sm" disabled={busy}>
                {t("save")}
              </Button>
            </div>
          ) : null}
        </div>
      </form>
    </li>
  );
}
