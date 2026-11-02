"use client";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";
import { section as sectionOf, type Field, type SectionKey } from "@/lib/pipeline";

export type ToolOption = { id: string; name: string; server: string; access: string };

export type ProviderOption = {
  id: string;
  name: string;
  capability: string;
  adapter: string;
  hosting: string;
  enabled: boolean;
};

const input =
  "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm disabled:opacity-60";
const label = "flex flex-col gap-1 text-[13px] font-medium";

function read(field: Field, form: FormData): unknown {
  const raw = form.get(field.name);
  switch (field.kind) {
    case "toggle":
      return raw === "on";
    case "number": {
      const s = String(raw ?? "").trim();
      if (!s) return field.optional ? null : field.min;
      return Number(s);
    }
    case "instance":
      return String(raw || "") || null;
    case "list":
      return String(raw || "")
        .split("\n")
        .map((x) => x.trim())
        .filter(Boolean);
    case "multi":
    case "instances":
      return form.getAll(field.name).map(String);
    case "tools":
      return form.getAll(field.name).map((id) => ({ tool_id: String(id), enabled: true }));
    default:
      return String(raw ?? "");
  }
}

/** Edits one section of the draft spec; saving replaces the draft (If-Match: chatbot version). */
export function SpecForm({
  botId,
  version,
  spec,
  sectionKey,
  providers,
  tools = [],
  canEdit,
}: {
  botId: string;
  version: number;
  spec: PipelineSpec;
  sectionKey: SectionKey;
  providers: ProviderOption[];
  /** Enabled tools of active MCP servers (Agent section). */
  tools?: ToolOption[];
  canEdit: boolean;
}) {
  const t = useTranslations("pipeline");
  const router = useRouter();
  const sec = sectionOf(sectionKey);
  const values = (spec[sec.spec] ?? {}) as unknown as Record<string, unknown>;
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = structuredClone(spec) as unknown as Record<string, Record<string, unknown>>;
    for (const f of sec.fields) next[sec.spec]![f.name] = read(f, form);
    setBusy(true);
    setState(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/pipeline/draft`, {
        method: "PUT",
        headers: { "If-Match": String(version) },
        body: JSON.stringify({ spec: next, change_note: String(form.get("change_note") || "") }),
      });
      setState({ ok: true, text: t("saved") });
      router.refresh();
    } catch (e) {
      setState({
        ok: false,
        text: t("saveFailed", { code: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  function control(f: Field) {
    const v = values[f.name];
    const id = `f-${f.name}`;
    const disabled = !canEdit;
    const title = t(`f.${f.name}.label`);
    const hint = t.has(`f.${f.name}.hint`) ? t(`f.${f.name}.hint`) : null;
    const help = hint ? <span className="text-xs font-normal text-fg-muted">{hint}</span> : null;
    switch (f.kind) {
      case "toggle":
        return (
          <label key={f.name} className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              name={f.name}
              defaultChecked={Boolean(v)}
              disabled={disabled}
              className="mt-1"
            />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">{title}</span>
              {help}
            </span>
          </label>
        );
      case "instance": {
        const fits = (p: ProviderOption) =>
          p.capability === f.capability && (!f.adapters || f.adapters.includes(p.adapter));
        const options = providers.filter(fits);
        // One chosen before the slot was checked stays visible, marked, so it can be replaced.
        const wrong = providers.find((p) => p.id === v && !fits(p));
        return (
          <label key={f.name} htmlFor={id} className={label}>
            {title}
            <select
              id={id}
              name={f.name}
              defaultValue={(v as string | null) ?? ""}
              disabled={disabled}
              className={input}
            >
              <option value="">{f.optional ? t("none") : t("choose")}</option>
              {wrong ? (
                <option value={wrong.id}>{t("wrongKind", { name: wrong.name })}</option>
              ) : null}
              {options.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.enabled}>
                  {p.name}
                  {p.hosting === "external" ? ` · ${t("external")}` : ""}
                </option>
              ))}
            </select>
            {help}
          </label>
        );
      }
      case "select":
        return (
          <label key={f.name} htmlFor={id} className={label}>
            {title}
            <select
              id={id}
              name={f.name}
              defaultValue={String(v ?? "")}
              disabled={disabled}
              className={input}
            >
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {t(`o.${o}`)}
                </option>
              ))}
            </select>
            {help}
          </label>
        );
      case "number":
        return (
          <label key={f.name} htmlFor={id} className={label}>
            {title}
            <input
              id={id}
              name={f.name}
              type="number"
              min={f.min}
              max={f.max}
              step={f.step ?? 1}
              defaultValue={v === null || v === undefined ? "" : String(v)}
              disabled={disabled}
              className={input}
            />
            {help}
          </label>
        );
      case "textarea":
        return (
          <label key={f.name} htmlFor={id} className={label}>
            {title}
            <textarea
              id={id}
              name={f.name}
              rows={f.rows ?? 4}
              defaultValue={String(v ?? "")}
              disabled={disabled}
              className="rounded-md border border-line-strong bg-surface p-3 text-sm"
            />
            {help}
          </label>
        );
      case "list":
        return (
          <label key={f.name} htmlFor={id} className={label}>
            {title}
            <textarea
              id={id}
              name={f.name}
              rows={4}
              defaultValue={((v as string[] | undefined) ?? []).join("\n")}
              disabled={disabled}
              className="rounded-md border border-line-strong bg-surface p-3 text-sm"
            />
            {help}
          </label>
        );
      case "multi": {
        const chosen = (v as string[] | undefined) ?? [];
        return (
          <fieldset key={f.name} className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium">{title}</legend>
            {f.options.map((o) => {
              const locked = f.locked?.includes(o);
              return (
                <label key={o} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    name={f.name}
                    value={o}
                    defaultChecked={chosen.includes(o) || locked}
                    disabled={disabled || locked}
                  />
                  {locked ? <input type="hidden" name={f.name} value={o} /> : null}
                  {t(`o.${o}`)}
                  {locked ? <span className="text-xs text-fg-muted">{t("locked")}</span> : null}
                </label>
              );
            })}
            {help}
          </fieldset>
        );
      }
      case "instances": {
        const chosen = (v as string[] | undefined) ?? [];
        const options = providers.filter((p) => p.capability === f.capability && p.enabled);
        return (
          // A list of providers: the whole row, so long names do not run into the next field.
          <fieldset
            key={f.name}
            className="col-span-full m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0"
          >
            <legend className="mb-1 text-[13px] font-medium">{title}</legend>
            {options.length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("none")}</p>
            ) : (
              options.map((p) => (
                <label key={p.id} className="flex min-w-0 items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    name={f.name}
                    value={p.id}
                    defaultChecked={chosen.includes(p.id)}
                    disabled={disabled}
                    className="mt-1"
                  />
                  <span className="min-w-0 break-words">
                    {p.name}
                    {p.hosting === "external" ? (
                      <span className="text-xs text-fg-muted"> · {t("external")}</span>
                    ) : null}
                  </span>
                </label>
              ))
            )}
            {help}
          </fieldset>
        );
      }
      case "tools": {
        const bound = ((v as { tool_id: string; enabled?: boolean }[] | undefined) ?? [])
          .filter((b) => b.enabled !== false)
          .map((b) => b.tool_id);
        const gone = bound.filter((id) => !tools.some((tool) => tool.id === id));
        return (
          <fieldset key={f.name} className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium">{title}</legend>
            {tools.length === 0 && gone.length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("noTools")}</p>
            ) : null}
            {tools.map((tool) => (
              <label key={tool.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  name={f.name}
                  value={tool.id}
                  defaultChecked={bound.includes(tool.id)}
                  disabled={disabled}
                />
                <span className="font-mono">{tool.name}</span>
                <span className="text-xs text-fg-muted">
                  {tool.server} · {t(`o.${tool.access}`)}
                </span>
              </label>
            ))}
            {gone.map((id) => (
              <label key={id} className="flex items-center gap-2 text-sm text-fg-muted">
                <input
                  type="checkbox"
                  name={f.name}
                  value={id}
                  defaultChecked
                  disabled={disabled}
                />
                <span className="font-mono">{id.slice(0, 8)}</span> · {t("toolGone")}
              </label>
            ))}
            {help}
          </fieldset>
        );
      }
      default:
        return (
          <label key={f.name} htmlFor={id} className={label}>
            {title}
            <input
              id={id}
              name={f.name}
              defaultValue={String(v ?? "")}
              disabled={disabled}
              className={`${input} font-mono`}
            />
            {help}
          </label>
        );
    }
  }

  return (
    <form
      onSubmit={save}
      aria-labelledby="section-title"
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <h2 id="section-title" className="m-0 text-lg font-bold">
        {t(`sections.${sectionKey}`)}
      </h2>
      {sec.runtimePhase ? (
        <p role="note" className="m-0 rounded-md bg-info-soft px-3 py-2 text-sm text-info">
          {t("runtimeLater", { phase: sec.runtimePhase })}
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
        {sec.fields.map(control)}
      </div>
      {canEdit ? (
        <div className="flex flex-wrap items-end gap-3 border-t border-divider pt-4">
          <label className={`${label} min-w-64 flex-1`}>
            {t("changeNote")}
            <input name="change_note" maxLength={2000} className={input} />
          </label>
          <Button type="submit" variant="primary" disabled={busy}>
            {t("saveDraft")}
          </Button>
        </div>
      ) : null}
      {state ? (
        <p
          role={state.ok ? "status" : "alert"}
          className={`m-0 text-sm ${state.ok ? "text-green" : "text-red"}`}
        >
          {state.text}
        </p>
      ) : null}
    </form>
  );
}
