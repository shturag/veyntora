"use client";

import { Badge, Button } from "@veyntora/ui";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Panel } from "@/components/admin/panel";
import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Tool = components["schemas"]["ToolOut"];
type Result = components["schemas"]["TestResult"];
type Source = components["schemas"]["TestSource"];
type Shown = Result & { sources: Source[]; blocks: string[]; advice: string[] };
type Prop = { type?: string; description?: string; enum?: unknown[]; default?: unknown };

const control = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const field = "flex flex-col gap-1.5 text-[13px] font-medium";

/** A tool's inputs as form values: text, numbers, yes/no, choices; anything else as JSON. */
function inputsOf(tool: Tool | undefined): [string, Prop, boolean][] {
  const schema = (tool?.input_schema ?? {}) as {
    properties?: Record<string, Prop>;
    required?: string[];
  };
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, p]) => [name, p, required.has(name)]);
}

function valueOf(p: Prop, raw: FormDataEntryValue | null): unknown {
  const text = String(raw ?? "").trim();
  if (p.type === "boolean") return raw === "on";
  if (text === "") return undefined;
  if (p.type === "integer" || p.type === "number") return Number(text);
  if (p.type === "array" || p.type === "object") return JSON.parse(text) as unknown;
  return text;
}

/** Try a read tool once and see exactly the sources Veyntora would give the model. */
export function ToolTester({ tools }: { tools: Tool[] }) {
  const t = useTranslations("tools");
  const router = useRouter();
  const usable = tools.filter((x) => x.present);
  const [toolId, setToolId] = useState(
    usable.find((x) => x.access === "read")?.id ?? usable[0]?.id ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Shown | null>(null);
  const tool = usable.find((x) => x.id === toolId);
  const readable = tool?.access === "read";

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tool) return;
    const form = new FormData(event.currentTarget);
    const args: Record<string, unknown> = {};
    try {
      for (const [name, p] of inputsOf(tool)) {
        const v = valueOf(p, form.get(name));
        if (v !== undefined) args[name] = v;
      }
    } catch {
      setError(t("testBadJson"));
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      let out = await api<Result>(`/v1/admin/tools/${tool.id}/test`, {
        method: "POST",
        body: JSON.stringify({ arguments: args }),
      });
      // The worker runs the call; the result arrives within a few seconds.
      for (let i = 0; i < 90 && out.status !== "done"; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        out = await api<Result>(`/v1/admin/tools/tests/${out.id}`);
      }
      if (out.status !== "done") setError(t("testTimeout"));
      else {
        setResult({
          ...out,
          sources: out.sources ?? [],
          blocks: out.blocks ?? [],
          advice: out.advice ?? [],
        });
      }
      router.refresh();
    } catch (e) {
      setError(t("failed", { reason: e instanceof Error ? e.message : "?" }));
    } finally {
      setBusy(false);
    }
  }

  const pages = result?.blocks.filter((b) => b === "page").length ?? 0;
  const texts = (result?.blocks.length ?? 0) - pages;
  return (
    <Panel id="tool-test" title={t("testTitle")} description={t("testText")}>
      <form onSubmit={run} className="flex flex-col gap-4" aria-label={t("testTitle")}>
        <label className={field}>
          {t("testTool")}
          <select
            value={toolId}
            onChange={(e) => {
              setToolId(e.target.value);
              setResult(null);
              setError(null);
            }}
            className={control}
          >
            {usable.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
                {x.access === "read" ? "" : ` (${t(`access.${x.access}`)}: ${t("testReadOnly")})`}
              </option>
            ))}
          </select>
        </label>
        {tool && readable ? (
          <div key={tool.id} className="grid grid-cols-2 gap-4 max-[800px]:grid-cols-1">
            {inputsOf(tool).map(([name, p, required]) => {
              const label = (
                <span>
                  <span className="font-mono">{name}</span>
                  {required ? <span className="text-red"> *</span> : null}
                </span>
              );
              const hint = p.description ? (
                <span className="text-xs font-normal text-fg-muted">{p.description}</span>
              ) : null;
              if (p.type === "boolean") {
                return (
                  <label key={name} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      name={name}
                      defaultChecked={p.default === true}
                      className="size-4"
                    />
                    {label}
                  </label>
                );
              }
              if (p.enum) {
                return (
                  <label key={name} className={field}>
                    {label}
                    <select
                      name={name}
                      defaultValue={String(p.default ?? "")}
                      required={required}
                      className={control}
                    >
                      {required ? null : <option value="" />}
                      {p.enum.map((v) => (
                        <option key={String(v)} value={String(v)}>
                          {String(v)}
                        </option>
                      ))}
                    </select>
                    {hint}
                  </label>
                );
              }
              const json = p.type === "array" || p.type === "object";
              return (
                <label key={name} className={json ? `${field} col-span-full` : field}>
                  {label}
                  {json ? (
                    <textarea
                      name={name}
                      rows={3}
                      required={required}
                      placeholder={p.type === "array" ? "[]" : "{}"}
                      className="rounded-md border border-line-strong bg-surface p-2 font-mono text-xs"
                    />
                  ) : (
                    <input
                      name={name}
                      type={p.type === "integer" || p.type === "number" ? "number" : "text"}
                      required={required}
                      defaultValue={p.default === undefined ? undefined : String(p.default)}
                      className={control}
                    />
                  )}
                  {hint}
                </label>
              );
            })}
          </div>
        ) : tool ? (
          <p className="m-0 text-sm text-fg-muted">{t("testWriteNote")}</p>
        ) : (
          <p className="m-0 text-sm text-fg-muted">{t("noTools")}</p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={busy || !readable}>
            {busy ? t("testRunning") : t("testRun")}
          </Button>
          <span className="text-xs text-fg-muted">{t("testLogged")}</span>
        </div>
      </form>

      {error ? (
        <p role="alert" className="m-0 rounded-md bg-red-soft px-3 py-2 text-sm text-red">
          {error}
        </p>
      ) : null}
      {result ? (
        <div role="status" className="flex flex-col gap-3 border-t border-line pt-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={result.ok ? "green" : "red"}>
              {result.ok ? t("testOk") : t("testFailed")}
            </Badge>
            {result.ms != null ? (
              <span className="text-fg-muted">{(result.ms / 1000).toFixed(1)} s</span>
            ) : null}
            {result.ok ? (
              <span className="text-fg-muted">
                {t("testSummary", {
                  sources: result.sources.length,
                  pages,
                  texts,
                  chars: result.chars,
                })}
              </span>
            ) : null}
          </div>
          {result.error ? (
            <pre className="m-0 rounded-md bg-sunken p-3 text-xs whitespace-pre-wrap">
              {result.error}
            </pre>
          ) : null}
          {result.advice.length ? (
            <ul className="m-0 flex list-none flex-col gap-1.5 rounded-md bg-amber-soft p-3 text-sm text-amber">
              {result.advice.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          ) : result.ok ? (
            <p className="m-0 text-sm text-green">{t("testGood")}</p>
          ) : null}
          {result.sources.length ? (
            <ol className="m-0 flex list-none flex-col gap-2 p-0">
              {result.sources.map((s) => (
                <li key={s.n} className="flex flex-col gap-1 rounded-md border border-line p-3">
                  <div className="flex items-start gap-2">
                    <span className="inline-flex size-5 shrink-0 items-center justify-center rounded bg-accent-soft text-[11px] font-semibold">
                      {s.n}
                    </span>
                    <span className="min-w-0 flex-1 font-medium break-words">{s.title}</span>
                    <span className="shrink-0 text-xs text-fg-muted">
                      {t("testChars", { chars: s.chars })}
                    </span>
                  </div>
                  {s.url ? (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="inline-flex items-center gap-1 self-start text-xs font-medium break-all"
                    >
                      {s.url}
                      <ExternalLink aria-hidden className="size-3 shrink-0" />
                    </a>
                  ) : (
                    <span className="text-xs text-fg-muted">{t("testNoAddress")}</span>
                  )}
                  <p className="m-0 line-clamp-4 border-l-2 border-line-strong pl-2 text-xs leading-relaxed whitespace-pre-wrap text-fg-secondary">
                    {s.text}
                  </p>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
