"use client";

import type { PipelineSpec } from "@veyntora/spec";
import { Badge, Button } from "@veyntora/ui";
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

// Fields that take the whole row: long text and lists of choices.
const WIDE = new Set<Field["kind"]>([
  "textarea",
  "list",
  "instances",
  "tools",
  "tool_ids",
  "multi",
]);

/** A group's fields in order; switches next to each other become one list. */
function blocks(fields: readonly Field[]): (Field | Field[])[] {
  const out: (Field | Field[])[] = [];
  for (const f of fields) {
    const last = out.at(-1);
    if (f.kind !== "toggle") out.push(f);
    else if (Array.isArray(last)) last.push(f);
    else out.push([f]);
  }
  return out;
}

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
    case "tool_ids":
      return form.getAll(field.name).map(String);
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

  const byName = new Map(sec.fields.map((f) => [f.name, f]));
  const groups = sec.groups.map(([key, names]) => ({
    key,
    fields: names.map((n) => byName.get(n)).filter((f): f is Field => f !== undefined),
  }));

  function control(f: Field) {
    const v = values[f.name];
    const id = `f-${f.name}`;
    const disabled = !canEdit;
    const title = t(`f.${f.name}.label`);
    const hint = t.has(`f.${f.name}.hint`) ? t(`f.${f.name}.hint`) : null;
    // Long words (setting names, URLs) wrap instead of running into the next field.
    const help = hint ? (
      <span className="text-xs font-normal [overflow-wrap:anywhere] text-fg-muted">{hint}</span>
    ) : null;
    switch (f.kind) {
      case "toggle":
        // A row of the group's list of switches.
        return (
          <label
            key={f.name}
            className="flex cursor-pointer items-start gap-3 px-4 py-3 text-sm hover:bg-sunken/50"
          >
            <input
              type="checkbox"
              name={f.name}
              defaultChecked={Boolean(v)}
              disabled={disabled}
              className="mt-0.5 size-4 shrink-0"
            />
            <span className="flex min-w-0 flex-col gap-0.5">
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
          <fieldset key={f.name} className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1.5 text-[13px] font-medium">{title}</legend>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-2">
              {f.options.map((o) => {
                const locked = f.locked?.includes(o);
                return (
                  <label
                    key={o}
                    className={`flex items-center gap-2.5 rounded-md border border-line px-3 py-2 text-sm ${locked ? "bg-sunken/60 text-fg-secondary" : "cursor-pointer hover:bg-sunken/50"}`}
                  >
                    <input
                      type="checkbox"
                      name={f.name}
                      value={o}
                      defaultChecked={chosen.includes(o) || locked}
                      disabled={disabled || locked}
                      className="size-4 shrink-0"
                    />
                    {locked ? <input type="hidden" name={f.name} value={o} /> : null}
                    <span className="min-w-0 flex-1">{t(`o.${o}`)}</span>
                    {locked ? <span className="text-xs text-fg-muted">{t("locked")}</span> : null}
                  </label>
                );
              })}
            </div>
            {help}
          </fieldset>
        );
      }
      case "instances": {
        const chosen = (v as string[] | undefined) ?? [];
        // Models people can switch to: the model for answers is always offered, so it is shown
        // first, ticked and fixed, and is not one of the choices.
        const fixed =
          f.name === "llm_instance_ids"
            ? providers.find((p) => p.id === spec.generation?.llm_instance_id)
            : undefined;
        const options = providers.filter(
          (p) => p.capability === f.capability && p.enabled && p.id !== fixed?.id,
        );
        return (
          <fieldset key={f.name} className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1.5 text-[13px] font-medium">{title}</legend>
            {options.length === 0 && !fixed ? (
              <p className="m-0 text-sm text-fg-muted">{t("none")}</p>
            ) : (
              <div className="flex flex-col divide-y divide-line rounded-md border border-line">
                {fixed ? (
                  <label className="flex min-w-0 items-center gap-3 px-4 py-2.5 text-sm">
                    <input type="checkbox" checked disabled className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1 font-mono text-[13px] break-words">
                      {fixed.name}
                    </span>
                    <Badge tone="neutral">{t("defaultModel")}</Badge>
                  </label>
                ) : null}
                {options.map((p) => (
                  <label
                    key={p.id}
                    className="flex min-w-0 cursor-pointer items-center gap-3 px-4 py-2.5 text-sm hover:bg-sunken/50"
                  >
                    <input
                      type="checkbox"
                      name={f.name}
                      value={p.id}
                      defaultChecked={chosen.includes(p.id)}
                      disabled={disabled}
                      className="size-4 shrink-0"
                    />
                    <span className="min-w-0 flex-1 font-mono text-[13px] break-words">
                      {p.name}
                    </span>
                    {p.hosting === "external" ? <Badge tone="amber">{t("external")}</Badge> : null}
                  </label>
                ))}
              </div>
            )}
            {help}
          </fieldset>
        );
      }
      case "tools":
      case "tool_ids": {
        const bound =
          f.kind === "tool_ids"
            ? ((v as string[] | undefined) ?? [])
            : ((v as { tool_id: string; enabled?: boolean }[] | undefined) ?? [])
                .filter((b) => b.enabled !== false)
                .map((b) => b.tool_id);
        // Knowledge tools only read: they run with every question, without an approval.
        const choices = f.kind === "tool_ids" ? tools.filter((x) => x.access === "read") : tools;
        const gone = bound.filter((id) => !choices.some((tool) => tool.id === id));
        return (
          <fieldset key={f.name} className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium">{title}</legend>
            {choices.length === 0 && gone.length === 0 ? (
              <p className="m-0 text-sm text-fg-muted">{t("noTools")}</p>
            ) : null}
            {choices.map((tool) => (
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
      className="flex min-w-0 flex-col rounded-lg border border-line bg-surface"
    >
      <header className="flex flex-col gap-1 border-b border-line px-6 py-4">
        <h2 id="section-title" className="m-0 text-lg font-bold">
          {t(`sections.${sectionKey}`)}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t(`sectionText.${sectionKey}`)}</p>
      </header>
      <div className="flex flex-col gap-5 px-6 py-5">
        {sec.runtimePhase ? (
          <p role="note" className="m-0 rounded-md bg-info-soft px-3 py-2 text-sm text-info">
            {t("runtimeLater", { phase: sec.runtimePhase })}
          </p>
        ) : null}
        {groups.map(({ key, fields }, i) => (
          <section
            key={key}
            aria-labelledby={`group-${key}`}
            className={`flex flex-col gap-4 ${i ? "border-t border-divider pt-5" : ""}`}
          >
            <h3
              id={`group-${key}`}
              className="m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase"
            >
              {t(`groups.${key}`)}
            </h3>
            <div className="grid grid-cols-2 items-start gap-x-6 gap-y-5 max-[900px]:grid-cols-1">
              {blocks(fields).map((b) =>
                Array.isArray(b) ? (
                  // Switches next to each other: one list, the whole row.
                  <div
                    key={b[0]!.name}
                    className="col-span-full flex flex-col divide-y divide-line rounded-md border border-line"
                  >
                    {b.map(control)}
                  </div>
                ) : (
                  <div key={b.name} className={WIDE.has(b.kind) ? "col-span-full" : "min-w-0"}>
                    {control(b)}
                  </div>
                ),
              )}
            </div>
          </section>
        ))}
      </div>
      {canEdit ? (
        <footer className="flex flex-col gap-3 rounded-b-lg border-t border-line bg-sunken/50 px-6 py-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className={`${label} min-w-64 flex-1`}>
              {t("changeNote")}
              <input
                name="change_note"
                maxLength={2000}
                placeholder={t("changeNoteHint")}
                className={input}
              />
            </label>
            <Button type="submit" variant="primary" disabled={busy}>
              {t("saveDraft")}
            </Button>
          </div>
          {state ? (
            <p
              role={state.ok ? "status" : "alert"}
              className={`m-0 text-sm ${state.ok ? "text-green" : "text-red"}`}
            >
              {state.text}
            </p>
          ) : null}
        </footer>
      ) : state ? (
        <p role="alert" className="m-0 px-6 pb-5 text-sm text-red">
          {state.text}
        </p>
      ) : null}
    </form>
  );
}
