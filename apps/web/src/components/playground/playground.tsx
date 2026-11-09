"use client";

import { Badge, Button } from "@veyntora/ui";
import { Zap } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState, type FormEvent, type ReactNode } from "react";

import { AnswerText } from "@/components/chat/answer";
import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Result = components["schemas"]["PlaygroundResult"];
type Step = components["schemas"]["PlaygroundStep"];
type Bot = { id: string; name: string; live: number | null };

const sectionTitle = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";

/** Question and chatbot; then the draft and live runs side by side, section by section. */
export function Playground({ bots, initialBot }: { bots: Bot[]; initialBot: string }) {
  const t = useTranslations("playground");
  const [botId, setBotId] = useState(initialBot);
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<Result[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bot = bots.find((b) => b.id === botId);
  const both = Boolean(bot?.live);

  async function run(e?: FormEvent) {
    e?.preventDefault();
    if (!question.trim() || busy) return;
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

  const live = results?.find((r) => r.version === "live");
  return (
    <div className="flex flex-col gap-5">
      <form
        aria-label={t("form")}
        onSubmit={run}
        className="flex flex-col rounded-lg border border-line bg-surface"
      >
        <div className="grid grid-cols-[minmax(0,20rem)_minmax(0,1fr)] gap-x-6 gap-y-4 p-5 max-[760px]:grid-cols-1">
          <label className="flex flex-col gap-1 text-[13px] font-medium">
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
          <div className="flex flex-col gap-1">
            <span className="text-[13px] font-medium">{t("compares")}</span>
            <span className="flex h-10 flex-wrap items-center gap-2 text-sm">
              <Badge tone="info">{t("version.draft")}</Badge>
              {both ? (
                <>
                  <span className="text-fg-muted">{t("vs")}</span>
                  <Badge tone="green">
                    {t("version.live")} v{bot?.live}
                  </Badge>
                </>
              ) : (
                <span className="text-xs text-fg-muted">{t("noLive")}</span>
              )}
              <span className="ml-auto flex items-center gap-1.5 text-xs text-fg-muted">
                <Zap aria-hidden className="size-3.5" />
                {t("fastOnly")}
              </span>
            </span>
          </div>
          <label className="col-span-full flex flex-col gap-1 text-[13px] font-medium">
            {t("question")}
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void run();
              }}
              rows={3}
              maxLength={8000}
              placeholder={t("questionPlaceholder")}
              className="resize-y rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
            />
          </label>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
          <span className="text-xs text-fg-muted">
            {t("asYou")} {t("modeLater")}
          </span>
          <span className="flex items-center gap-3">
            <span className="text-xs text-fg-muted max-[560px]:hidden">{t("shortcut")}</span>
            <Button type="submit" variant="primary" disabled={busy || !question.trim()}>
              {busy ? t("running") : both ? t("runBoth") : t("runDraft")}
            </Button>
          </span>
        </footer>
        {error ? (
          <p role="alert" className="m-0 border-t border-line px-5 py-3 text-sm text-red">
            {error}
          </p>
        ) : null}
      </form>
      {results ? (
        // One grid row per section, shared by both columns (subgrid), so the draft's
        // answer, sources and steps sit level with the live version's.
        <section
          aria-label={t("results")}
          className={`grid grid-rows-[repeat(5,auto)] gap-x-5 ${results.length > 1 ? "grid-cols-2 max-[900px]:grid-cols-1" : "grid-cols-1"}`}
        >
          {results.map((r) => (
            <RunColumn
              key={r.version}
              result={r}
              baseline={r.version === "draft" && live ? live : null}
            />
          ))}
        </section>
      ) : null}
    </div>
  );
}

function RunColumn({ result: r, baseline }: { result: Result; baseline: Result | null }) {
  const t = useTranslations("playground");
  const format = useFormatter();
  const ran = r.outcome !== "refused" && r.outcome !== "error";
  const seconds = (ms: number) => `${format.number(ms / 1000, { maximumFractionDigits: 2 })} s`;
  const total = Math.max(1, ...r.steps.map((s) => s.ms));
  // Compared with the live version: lower latency and tokens, higher groundedness are better.
  const delta = (now: number | null | undefined, then: number | null | undefined) =>
    now == null || then == null ? null : now - then;
  const dLatency = delta(r.latency_ms, baseline?.latency_ms);
  const dTokens = delta(
    r.tokens_in + r.tokens_out,
    baseline ? baseline.tokens_in + baseline.tokens_out : null,
  );
  const dGrounded = delta(r.groundedness, baseline?.groundedness);
  return (
    <article
      aria-label={t(`version.${r.version}`)}
      className="row-span-5 grid grid-rows-subgrid gap-0 overflow-hidden rounded-lg border border-line bg-surface max-[900px]:mb-5"
    >
      <header className="flex flex-col gap-3 border-b border-line px-5 py-4">
        <span className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 text-base font-semibold">
            {t(`version.${r.version}`)}
            {r.version_number ? ` v${r.version_number}` : ""}
          </h2>
          <span className="flex items-center gap-2 text-xs text-fg-muted">
            {r.search_type ? t("searchLine", { search: r.search_type, k: r.top_k ?? 0 }) : null}
            <Badge
              tone={
                r.outcome === "answered" ? "green" : r.outcome === "no_answer" ? "neutral" : "red"
              }
            >
              {t(`outcome.${r.outcome}` as "outcome.answered")}
            </Badge>
          </span>
        </span>
        {ran ? (
          <dl className="m-0 grid grid-cols-3 gap-3">
            <Metric
              label={t("latency")}
              value={r.latency_ms == null ? "–" : seconds(r.latency_ms)}
              change={
                dLatency == null || !baseline
                  ? null
                  : {
                      text: `${dLatency > 0 ? "+" : "−"}${seconds(Math.abs(dLatency))}`,
                      better: dLatency < 0,
                      same: Math.abs(dLatency) < 50,
                    }
              }
            />
            <Metric
              label={t("tokens")}
              value={format.number(r.tokens_in + r.tokens_out)}
              change={
                dTokens == null || !baseline
                  ? null
                  : {
                      text: `${dTokens > 0 ? "+" : "−"}${format.number(Math.abs(dTokens))}`,
                      better: dTokens < 0,
                      same: dTokens === 0,
                    }
              }
            />
            <Metric
              label={t("grounded")}
              value={
                r.groundedness == null ? "–" : format.number(r.groundedness, { style: "percent" })
              }
              change={
                dGrounded == null || !baseline
                  ? null
                  : {
                      text: t("points", {
                        sign: dGrounded > 0 ? "+" : "−",
                        n: Math.round(Math.abs(dGrounded) * 100),
                      }),
                      better: dGrounded > 0,
                      same: Math.round(dGrounded * 100) === 0,
                    }
              }
            />
          </dl>
        ) : null}
      </header>

      <Part title={ran ? t("answer") : t("notRun")}>
        <div className="rounded-md border border-line bg-sunken/40 p-4">
          {ran ? (
            <AnswerText
              text={r.text}
              meta={{ outcome: r.outcome as "answered" }}
              className="text-sm leading-relaxed"
            />
          ) : (
            <p className="m-0 text-sm whitespace-pre-wrap">{r.text}</p>
          )}
        </div>
        {r.warning ? <p className="m-0 text-xs text-amber">{r.warning}</p> : null}
        {r.external_egress ? <p className="m-0 text-xs text-fg-muted">{t("external")}</p> : null}
        {r.rerank_skipped ? (
          <p className="m-0 text-xs text-fg-muted">{t("rerankSkipped")}</p>
        ) : null}
      </Part>

      <Part title={t("sources")}>
        {r.sources.length ? (
          <ol className="m-0 flex list-none flex-col divide-y divide-divider p-0">
            {r.sources.map((s) => (
              <li
                key={s.n}
                className="grid grid-cols-[1.75rem_minmax(0,1fr)_auto] items-start gap-2 py-2 text-sm"
              >
                <span className="mt-0.5 flex h-5 min-w-5 items-center justify-center rounded-sm bg-accent-soft text-xs font-semibold text-accent">
                  {s.n}
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-medium" title={s.title}>
                    {s.title}
                  </span>
                  <span className="truncate text-xs text-fg-muted">
                    {[s.section, s.page ? t("page", { page: s.page }) : null]
                      .filter(Boolean)
                      .join(" · ") || " "}
                  </span>
                </span>
                <span className="flex flex-col items-end gap-0.5">
                  <span className="text-xs text-fg-secondary tabular-nums">
                    {format.number(s.score, { maximumFractionDigits: 2 })}
                  </span>
                  {s.cited ? <Badge tone="info">{t("cited")}</Badge> : null}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="m-0 text-sm text-fg-muted">{t("noSources")}</p>
        )}
      </Part>

      <Part title={t("steps")}>
        {r.steps.length ? (
          <ol className="m-0 flex list-none flex-col gap-2 p-0">
            {r.steps.map((s, i) => (
              <li
                key={`${s.name}-${i}`}
                className="grid grid-cols-[7.5rem_minmax(0,1fr)_3.5rem] items-center gap-3 text-sm"
              >
                <span className="truncate">{t(`step.${s.name}` as "step.retrieve")}</span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span
                    className="truncate text-xs text-fg-muted"
                    title={stepDetail(s, t("skipped"))}
                  >
                    {stepDetail(s, t("skipped")) || " "}
                  </span>
                  <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-sunken">
                    <span
                      className="block h-full rounded-full bg-accent"
                      style={{ width: `${Math.max(2, (s.ms / total) * 100)}%` }}
                    />
                  </span>
                </span>
                <span className="text-right text-xs text-fg-secondary tabular-nums">
                  {seconds(s.ms)}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="m-0 text-sm text-fg-muted">{t("noSteps")}</p>
        )}
      </Part>
      <span aria-hidden />
    </article>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 border-b border-divider px-5 py-4">
      <h3 className={sectionTitle}>{title}</h3>
      {children}
    </div>
  );
}

function Metric({
  label,
  value,
  change,
}: {
  label: string;
  value: string;
  change: { text: string; better: boolean; same: boolean } | null;
}) {
  return (
    <div className="flex flex-col rounded-md bg-sunken px-3 py-2">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="m-0 flex items-baseline gap-2">
        <span className="text-sm font-semibold tabular-nums">{value}</span>
        {change && !change.same ? (
          <span className={`text-xs tabular-nums ${change.better ? "text-green" : "text-red"}`}>
            {change.text}
          </span>
        ) : null}
      </dd>
    </div>
  );
}

/** A short note of what the step decided, from its trace attributes. */
function stepDetail(s: Step, skipped: string): string {
  const a = s.attrs as Record<string, unknown>;
  switch (s.name) {
    case "retrieve":
      return `${String(a.search)} · ${String(a.candidates)}`;
    case "rerank":
      return a.skipped ? skipped : `→ ${String(a.kept)}`;
    case "pii":
      return String(a.found);
    case "input_check":
    case "output_check":
      return String(a.action);
    case "generate":
    case "rewrite":
      return String(a["gen_ai.request.model"] ?? "");
    default:
      return "";
  }
}
