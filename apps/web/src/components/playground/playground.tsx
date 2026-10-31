"use client";

import { Badge, Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Result = components["schemas"]["PlaygroundResult"];
type Step = components["schemas"]["PlaygroundStep"];
type Bot = { id: string; name: string; live: number | null };

const MODES = ["fast", "agent", "auto"] as const;

/** Question, chatbot and mode; then the draft and live runs side by side. */
export function Playground({ bots, initialBot }: { bots: Bot[]; initialBot: string }) {
  const t = useTranslations("playground");
  const [botId, setBotId] = useState(initialBot);
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<Result[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bot = bots.find((b) => b.id === botId);
  const both = Boolean(bot?.live);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    setResults(null);
    try {
      setResults(
        await api<Result[]>("/v1/admin/playground/run", {
          method: "POST",
          body: JSON.stringify({
            chatbot_id: botId,
            question,
            versions: both ? ["draft", "live"] : ["draft"],
          }),
        }),
      );
    } catch (err) {
      setError(t("failed", { reason: err instanceof Error ? err.message : "?" }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <form
        aria-label={t("form")}
        onSubmit={run}
        className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap gap-4">
          <label className="flex min-w-[220px] flex-col gap-1 text-sm font-medium">
            {t("chatbot")}
            <select
              value={botId}
              onChange={(e) => {
                setBotId(e.target.value);
                setResults(null);
              }}
              className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal"
            >
              {bots.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
            <legend className="mb-1 p-0 text-sm font-medium">{t("mode")}</legend>
            <div className="flex gap-1 rounded-md border border-line-strong p-0.5">
              {MODES.map((m) => (
                <label
                  key={m}
                  title={m === "fast" ? undefined : t("modeLater")}
                  className={`flex h-9 items-center gap-1 rounded px-3 text-sm ${m === "fast" ? "bg-accent-soft font-medium" : "text-fg-muted"}`}
                >
                  <input
                    type="radio"
                    name="mode"
                    value={m}
                    defaultChecked={m === "fast"}
                    disabled={m !== "fast"}
                    className="sr-only"
                  />
                  {t(`modes.${m}`)}
                </label>
              ))}
            </div>
            <span className="text-xs text-fg-muted">{t("modeLater")}</span>
          </fieldset>
        </div>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t("question")}
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            maxLength={8000}
            placeholder={t("questionPlaceholder")}
            className="rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
          />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={busy || !question.trim()}>
            {busy ? t("running") : both ? t("runBoth") : t("runDraft")}
          </Button>
          {!both ? <span className="text-xs text-fg-muted">{t("noLive")}</span> : null}
          <span className="text-xs text-fg-muted">{t("asYou")}</span>
        </div>
        {error ? (
          <p role="alert" className="m-0 text-sm text-red">
            {error}
          </p>
        ) : null}
      </form>
      {results ? (
        <section
          aria-label={t("results")}
          className={`grid items-start gap-5 ${results.length > 1 ? "grid-cols-2 max-[900px]:grid-cols-1" : "grid-cols-1"}`}
        >
          {results.map((r) => (
            <RunColumn key={r.version} result={r} />
          ))}
        </section>
      ) : null}
    </div>
  );
}

function RunColumn({ result: r }: { result: Result }) {
  const t = useTranslations("playground");
  const format = useFormatter();
  const ran = r.outcome !== "refused" && r.outcome !== "error";
  const seconds = (ms: number) => `${format.number(ms / 1000, { maximumFractionDigits: 2 })} s`;
  const grounded =
    r.groundedness == null ? "–" : format.number(r.groundedness, { style: "percent" });
  return (
    <article
      aria-label={t(`version.${r.version}`)}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">
          {t(`version.${r.version}`)}
          {r.version_number ? ` v${r.version_number}` : ""}
        </h2>
        <span className="flex items-center gap-2 text-xs text-fg-muted">
          {r.search_type ? `${r.search_type} · top-k ${r.top_k}` : null}
          <Badge
            tone={
              r.outcome === "answered" ? "green" : r.outcome === "no_answer" ? "neutral" : "red"
            }
          >
            {t(`outcome.${r.outcome}` as "outcome.answered")}
          </Badge>
        </span>
      </header>
      {ran ? (
        <dl className="m-0 grid grid-cols-3 gap-3">
          <Metric label={t("latency")} value={r.latency_ms == null ? "–" : seconds(r.latency_ms)} />
          <Metric label={t("tokens")} value={format.number(r.tokens_in + r.tokens_out)} />
          <Metric label={t("grounded")} value={grounded} />
        </dl>
      ) : null}
      {r.steps.length ? (
        <div className="flex flex-col gap-1">
          <h3 className="m-0 text-sm font-semibold">{t("steps")}</h3>
          <ol className="m-0 flex list-none flex-col p-0">
            {r.steps.map((s, i) => (
              <li
                key={`${s.name}-${i}`}
                className="flex justify-between gap-3 border-t border-line py-1.5 text-sm"
              >
                <span>
                  {t(`step.${s.name}` as "step.retrieve")}
                  <span className="text-fg-muted">{stepDetail(s, t("skipped"))}</span>
                </span>
                <span className="shrink-0 tabular-nums text-fg-muted">{seconds(s.ms)}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {r.sources.length ? (
        <div className="flex flex-col gap-1">
          <h3 className="m-0 text-sm font-semibold">{t("sources")}</h3>
          <ol className="m-0 flex list-none flex-col p-0">
            {r.sources.map((s) => (
              <li
                key={s.n}
                className="flex justify-between gap-3 border-t border-line py-1.5 text-sm"
              >
                <span className="min-w-0 truncate">
                  [{s.n}] {s.title}
                  {s.section ? ` · ${s.section}` : ""}
                  {s.page ? ` · p${s.page}` : ""}
                  {s.cited ? <span className="text-fg-muted"> · {t("cited")}</span> : null}
                </span>
                <span className="shrink-0 tabular-nums text-fg-muted">
                  {format.number(s.score, { maximumFractionDigits: 2 })}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      <div className="flex flex-col gap-1">
        <h3 className="m-0 text-sm font-semibold">{ran ? t("answer") : t("notRun")}</h3>
        <p className="m-0 whitespace-pre-wrap rounded-md bg-sunken p-3 text-sm">{r.text}</p>
        {r.warning ? <p className="m-0 text-xs text-amber">{r.warning}</p> : null}
        {r.external_egress ? <p className="m-0 text-xs text-fg-muted">{t("external")}</p> : null}
        {r.rerank_skipped ? (
          <p className="m-0 text-xs text-fg-muted">{t("rerankSkipped")}</p>
        ) : null}
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col rounded-md bg-sunken px-3 py-2">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="m-0 text-sm font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/** A short note of what the step decided, from its trace attributes. */
function stepDetail(s: Step, skipped: string): string {
  const a = s.attrs as Record<string, unknown>;
  switch (s.name) {
    case "retrieve":
      return ` · ${String(a.search)} · ${String(a.candidates)}`;
    case "rerank":
      return a.skipped ? ` · ${skipped}` : ` · → ${String(a.kept)}`;
    case "pii":
      return ` · ${String(a.found)}`;
    case "input_check":
    case "output_check":
      return ` · ${String(a.action)}`;
    case "generate":
    case "rewrite":
      return ` · ${String(a["gen_ai.request.model"] ?? "")}`;
    default:
      return "";
  }
}
