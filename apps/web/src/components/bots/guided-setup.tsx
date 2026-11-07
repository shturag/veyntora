"use client";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

type Provider = { id: string; name: string; capability: string; hosting: string };
type Group = { id: string; name: string };
type Ref = string | null;
type Mode = "auto" | "fast" | "agent";
// The parts of the draft the questions decide (the API returns every section filled in).
type Draft = {
  ingestion: { parser_instance_id: Ref; embedding_instance_id: Ref };
  retrieval: { enabled: boolean; embedding_instance_id: Ref; vector_store_instance_id: Ref };
  rerank: { enabled: boolean; reranker_instance_id: Ref };
  generation: { llm_instance_id: Ref; system_prompt: string };
  agent: { llm_instance_id: Ref };
  router: { allowed_modes: Mode[]; default_mode: Mode };
  flow: { custom: boolean; nodes: FlowNode[]; edges: FlowEdge[] };
  chat: { llm_instance_ids: string[]; thinking: boolean };
};
type FlowNode = {
  id: string;
  type: string;
  label: string;
  x: number;
  y: number;
  note: string;
  config: Record<string, unknown>;
  provider_instance_id: Ref;
};
type FlowEdge = { source: string; target: string; label: string };

const control = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const field = "flex flex-col gap-1 text-[13px] font-medium";
const card = (on: boolean) =>
  `flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm ${on ? "border-accent bg-accent-soft" : "border-line-strong hover:bg-sunken"}`;

/** The standard pipeline's picture for these answers (positions are laid out on load). */
function picture(docs: boolean, rerank: boolean, tasks: boolean, t: (k: string) => string) {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  const add = (id: string, type: string, label: string, config: Record<string, unknown> = {}) =>
    nodes.push({ id, type, label, x: 0, y: 0, note: "", config, provider_instance_id: null });
  const link = (source: string, target: string, label = "") =>
    edges.push({ source, target, label });
  add("input", "input", t("pic.input"));
  let from = "input";
  if (tasks) {
    add("router", "router", t("pic.router"));
    link("input", "router");
    from = "router";
  }
  const fast = tasks ? "fast" : "";
  if (docs) {
    add("retriever", "retriever", t("pic.retriever"));
    link(from, "retriever", fast);
    let last = "retriever";
    if (rerank) {
      add("reranker", "reranker", t("pic.reranker"));
      link("retriever", "reranker");
      last = "reranker";
    }
    add("llm", "llm", t("pic.llm"));
    link(last, "llm");
    add("guardrail", "guardrail", t("pic.grounded"), { check: "grounded" });
    link("llm", "guardrail");
  } else {
    add("llm", "llm", t("pic.chat"));
    link(from, "llm", fast);
  }
  if (tasks) {
    add("agent_llm", "agent_llm", t("pic.agent"));
    add("tools", "mcp_tool", t("pic.tools"));
    link("router", "agent_llm", "agent");
    link("agent_llm", "tools");
    link("tools", "agent_llm");
  }
  add("output", "output", t("pic.output"));
  const end = docs ? "guardrail" : "llm";
  link(end, "output");
  if (tasks) link("agent_llm", docs ? "guardrail" : "output");
  return { custom: false, nodes, edges };
}

/**
 * Set a chatbot up by saying what it should do: the answers decide its modes, which steps
 * run and which providers it needs, and only those are asked for. Everything can still be
 * changed afterwards, on the forms or in the visual editor.
 */
export function GuidedSetup({
  botId,
  version,
  spec,
  providers,
  experts,
  next,
  tune,
  onDone,
}: {
  botId: string;
  version: number;
  spec: PipelineSpec;
  providers: Provider[];
  /** Expert teams (null: the reader may not change who the chatbot hands questions to). */
  experts: { teams: Group[]; groups: Group[] } | null;
  /** Where to go after saving (the wizard); otherwise the page refreshes. */
  next?: string;
  /** Where "Save and fine-tune" goes after saving (the wizard's advanced settings). */
  tune?: string;
  onDone?: () => void;
}) {
  const t = useTranslations("guided");
  const router = useRouter();
  const draft = spec as unknown as Draft;
  const [docs, setDocs] = useState(draft.retrieval.enabled !== false);
  // A new chatbot allows every mode but has no agent model yet: tasks start unticked.
  const [tasks, setTasks] = useState(
    draft.router.allowed_modes.includes("agent") && !!draft.agent.llm_instance_id,
  );
  const [rerank, setRerank] = useState(draft.rerank.enabled && !!draft.rerank.reranker_instance_id);
  const [handoff, setHandoff] = useState((experts?.teams.length ?? 0) > 0);
  const [teams, setTeams] = useState<string[]>(experts?.teams.map((g) => g.id) ?? []);
  const [picked, setPicked] = useState({
    llm: draft.generation.llm_instance_id ?? "",
    agent: draft.agent.llm_instance_id ?? "",
    embedding: draft.ingestion.embedding_instance_id ?? "",
    parser: draft.ingestion.parser_instance_id ?? "",
    store: draft.retrieval.vector_store_instance_id ?? "",
    reranker: draft.rerank.reranker_instance_id ?? "",
  });
  const suggested = () =>
    [t(docs ? "prompt.docs" : "prompt.general"), tasks ? t("prompt.tasks") : ""]
      .filter(Boolean)
      .join(" ");
  // The suggestion follows the answers until the admin writes their own prompt.
  const [prompt, setPrompt] = useState(draft.generation.system_prompt);
  const shownPrompt = prompt || suggested();
  // General chat: models people may switch between, and the thinking switch.
  const [choices, setChoices] = useState<string[]>(draft.chat?.llm_instance_ids ?? []);
  const [thinkingSwitch, setThinkingSwitch] = useState(Boolean(draft.chat?.thinking));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const of = (cap: string) => providers.filter((p) => p.capability === cap);
  const needed: { key: keyof typeof picked; cap: string; optional?: boolean }[] = [
    { key: "llm", cap: "llm" },
    ...(tasks ? [{ key: "agent" as const, cap: "llm", optional: true }] : []),
    ...(docs
      ? [
          { key: "embedding" as const, cap: "embedding" },
          { key: "parser" as const, cap: "parser" },
          { key: "store" as const, cap: "vector_store" },
          ...(rerank ? [{ key: "reranker" as const, cap: "reranker" }] : []),
        ]
      : []),
  ];
  const external = needed
    .map((n) => providers.find((p) => p.id === picked[n.key]))
    .filter((p): p is Provider => !!p && p.hosting === "external");

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const target = submitter?.value === "tune" && tune ? tune : next;
    const next_ = structuredClone(draft);
    const ref = (v: string) => v || null;
    next_.retrieval.enabled = docs;
    next_.generation.llm_instance_id = ref(picked.llm);
    next_.generation.system_prompt = shownPrompt.trim();
    if (docs) {
      next_.ingestion.parser_instance_id = ref(picked.parser);
      next_.ingestion.embedding_instance_id = ref(picked.embedding);
      next_.retrieval.embedding_instance_id = ref(picked.embedding);
      next_.retrieval.vector_store_instance_id = ref(picked.store);
    }
    next_.rerank.enabled = docs && rerank;
    if (docs && rerank) next_.rerank.reranker_instance_id = ref(picked.reranker);
    // Tasks use the agent; its model is the answers' model unless another is chosen.
    next_.agent.llm_instance_id = tasks
      ? ref(picked.agent || picked.llm)
      : next_.agent.llm_instance_id;
    const modes: Mode[] = tasks ? ["auto", "fast", "agent"] : ["fast"];
    next_.router.default_mode = tasks ? "auto" : "fast";
    next_.router.allowed_modes = modes;
    next_.flow = picture(docs, docs && rerank, tasks, (k) => t(k));
    next_.chat = {
      llm_instance_ids: docs
        ? (next_.chat?.llm_instance_ids ?? [])
        : choices.filter((i) => i !== picked.llm),
      thinking: docs ? Boolean(next_.chat?.thinking) : thinkingSwitch,
    };
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/pipeline/draft`, {
        method: "PUT",
        headers: { "If-Match": String(version) },
        body: JSON.stringify({ spec: next_, change_note: "set up with guided questions" }),
      });
      if (experts) {
        await api(`/v1/admin/chatbots/${botId}/experts`, {
          method: "PUT",
          body: JSON.stringify({ group_ids: docs && handoff ? teams : [] }),
        });
      }
      if (target) router.push(target);
      else {
        router.refresh();
        onDone?.();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      aria-label={t("title")}
      onSubmit={save}
      className="flex flex-col gap-5 rounded-lg border border-line bg-surface p-5"
    >
      <div>
        <h2 className="m-0 text-base font-semibold">{t("title")}</h2>
        <p className="m-0 text-sm text-fg-secondary">{t("intro")}</p>
      </div>

      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-2 p-0 text-sm font-semibold">1. {t("q.knowledge")}</legend>
        <div className="grid grid-cols-2 gap-2 max-[760px]:grid-cols-1">
          <label className={card(docs)}>
            <input type="radio" name="knowledge" checked={docs} onChange={() => setDocs(true)} />
            <span className="flex flex-col">
              <span className="font-medium">{t("docs.title")}</span>
              <span className="text-xs text-fg-muted">{t("docs.hint")}</span>
            </span>
          </label>
          <label className={card(!docs)}>
            <input type="radio" name="knowledge" checked={!docs} onChange={() => setDocs(false)} />
            <span className="flex flex-col">
              <span className="font-medium">{t("general.title")}</span>
              <span className="text-xs text-fg-muted">{t("general.hint")}</span>
            </span>
          </label>
        </div>
        {!docs ? (
          <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
            {t.rich("general.rule", {
              link: (c) => <Link href={`/admin/chatbots/${botId}/access`}>{c}</Link>,
            })}
          </p>
        ) : null}
      </fieldset>

      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-2 p-0 text-sm font-semibold">2. {t("q.more")}</legend>
        <label className={card(tasks)}>
          <input type="checkbox" checked={tasks} onChange={(e) => setTasks(e.target.checked)} />
          <span className="flex flex-col">
            <span className="font-medium">{t("tasks.title")}</span>
            <span className="text-xs text-fg-muted">{t("tasks.hint")}</span>
          </span>
        </label>
        {!docs ? (
          <div className={card(choices.length > 0)}>
            <span className="flex flex-1 flex-col gap-2">
              <span className="flex flex-col">
                <span className="font-medium">{t("models.title")}</span>
                <span className="text-xs text-fg-muted">{t("models.hint")}</span>
              </span>
              <span className="flex flex-wrap gap-x-4 gap-y-1">
                {of("llm")
                  .filter((p) => p.id !== picked.llm)
                  .map((p) => (
                    <label key={p.id} className="flex items-center gap-1.5 text-sm">
                      <input
                        type="checkbox"
                        checked={choices.includes(p.id)}
                        onChange={(e) =>
                          setChoices((l) =>
                            e.target.checked ? [...l, p.id] : l.filter((x) => x !== p.id),
                          )
                        }
                      />
                      {p.name}
                      {p.hosting === "external" ? (
                        <span className="text-xs text-fg-muted">· {t("external")}</span>
                      ) : null}
                    </label>
                  ))}
                {of("llm").filter((p) => p.id !== picked.llm).length === 0 ? (
                  <span className="text-xs text-fg-muted">{t("models.none")}</span>
                ) : null}
              </span>
            </span>
          </div>
        ) : null}
        {!docs ? (
          <label className={card(thinkingSwitch)}>
            <input
              type="checkbox"
              checked={thinkingSwitch}
              onChange={(e) => setThinkingSwitch(e.target.checked)}
            />
            <span className="flex flex-col">
              <span className="font-medium">{t("thinking.title")}</span>
              <span className="text-xs text-fg-muted">{t("thinking.hint")}</span>
            </span>
          </label>
        ) : null}
        {docs ? (
          <label className={card(rerank)}>
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
            <span className="flex flex-col">
              <span className="font-medium">{t("rerank.title")}</span>
              <span className="text-xs text-fg-muted">{t("rerank.hint")}</span>
            </span>
          </label>
        ) : null}
        {docs && experts ? (
          <div className={card(handoff)}>
            <input
              type="checkbox"
              aria-labelledby="handoff-title"
              checked={handoff}
              onChange={(e) => setHandoff(e.target.checked)}
            />
            <span className="flex flex-1 flex-col gap-2">
              <span className="flex flex-col">
                <span id="handoff-title" className="font-medium">
                  {t("handoff.title")}
                </span>
                <span className="text-xs text-fg-muted">{t("handoff.hint")}</span>
              </span>
              {handoff ? (
                experts.groups.length ? (
                  <span className="flex flex-wrap gap-x-4 gap-y-1">
                    {experts.groups.map((g) => (
                      <label key={g.id} className="flex items-center gap-1.5 text-sm">
                        <input
                          type="checkbox"
                          checked={teams.includes(g.id)}
                          onChange={(e) =>
                            setTeams((l) =>
                              e.target.checked ? [...l, g.id] : l.filter((x) => x !== g.id),
                            )
                          }
                        />
                        {g.name}
                      </label>
                    ))}
                  </span>
                ) : (
                  <span className="text-xs text-fg-muted">{t("handoff.noGroups")}</span>
                )
              ) : null}
            </span>
          </div>
        ) : null}
      </fieldset>

      <fieldset className="m-0 flex flex-col gap-3 border-0 p-0">
        <legend className="mb-1 p-0 text-sm font-semibold">3. {t("q.providers")}</legend>
        <p className="m-0 text-xs text-fg-muted">{t("providersHint")}</p>
        <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
          {needed.map((n) => {
            const options = of(n.cap);
            return (
              <label key={n.key} className={field}>
                {t(`need.${n.key}`)}
                {options.length ? (
                  <select
                    value={picked[n.key]}
                    required={!n.optional}
                    onChange={(e) => setPicked({ ...picked, [n.key]: e.target.value })}
                    className={control}
                  >
                    <option value="">{n.optional ? t("sameAsAnswers") : t("choose")}</option>
                    {options.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                        {p.hosting === "external" ? ` · ${t("external")}` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="flex h-10 items-center justify-between gap-2 rounded-md border border-dashed border-line-strong px-3 text-sm font-normal text-fg-muted">
                    {t("noneYet")}
                    <Link href="/admin/providers/new" className="text-sm">
                      {t("addProvider")}
                    </Link>
                  </span>
                )}
                <span className="text-xs font-normal text-fg-muted">{t(`needHint.${n.key}`)}</span>
              </label>
            );
          })}
        </div>
        {external.length ? (
          <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
            {t.rich("externalRule", {
              names: external.map((p) => p.name).join(", "),
              link: (c) => <Link href={`/admin/chatbots/${botId}/access`}>{c}</Link>,
            })}
          </p>
        ) : null}
      </fieldset>

      <label className={field}>
        <span className="text-sm font-semibold">4. {t("q.prompt")}</span>
        <textarea
          rows={3}
          value={shownPrompt}
          required
          onChange={(e) => setPrompt(e.target.value)}
          className="rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
        />
        <span className="text-xs font-normal text-fg-muted">{t("promptHint")}</span>
      </label>

      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={busy}>
          {next ? t("saveContinue") : t("apply")}
        </Button>
        {tune ? (
          <Button type="submit" value="tune" disabled={busy}>
            {t("saveTune")}
          </Button>
        ) : null}
        <span className="text-xs text-fg-muted">{t("afterwards")}</span>
      </div>
    </form>
  );
}
