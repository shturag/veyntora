"use client";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { NewTabLink, useRefreshOnFocus } from "@/components/new-tab-link";

import { api } from "@/lib/chat";

import type { DataRule } from "./data-rules";

type Provider = { id: string; name: string; capability: string; hosting: string };
type Group = { id: string; name: string };
type Ref = string | null;
type Mode = "auto" | "fast" | "agent";
// The parts of the draft the questions decide (the API returns every section filled in).
type Draft = {
  ingestion: {
    parser_instance_id: Ref;
    embedding_instance_id: Ref;
    describe_images: boolean;
    vision_instance_id: Ref;
  };
  retrieval: { enabled: boolean; embedding_instance_id: Ref; vector_store_instance_id: Ref };
  rerank: { enabled: boolean; reranker_instance_id: Ref };
  generation: { llm_instance_id: Ref; system_prompt: string };
  agent: { llm_instance_id: Ref };
  router: { allowed_modes: Mode[]; default_mode: Mode };
  flow: { custom: boolean; nodes: FlowNode[]; edges: FlowEdge[] };
  chat: {
    llm_instance_ids: string[];
    thinking: boolean;
    attachments: boolean;
    web_search_instance_id: Ref;
    code_instance_id: Ref;
  };
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

// Something to decide: neutral. Something only another person can unblock: amber.
const ruleNote =
  "m-0 flex flex-col gap-2 rounded-md border border-line bg-sunken px-3 py-2.5 text-sm text-fg-secondary";
const ruleBlocked = "m-0 rounded-md bg-amber-soft px-3 py-2.5 text-sm text-amber";
const ruleCheck = "flex items-start gap-2 text-sm font-medium text-fg";

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
  rule,
  canAllow,
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
  /** The chatbot's data rule: general chat and external providers need it to allow them. */
  rule: DataRule;
  /** Whether the reader may change the data rule (governance editors). */
  canAllow: boolean;
  onDone?: () => void;
}) {
  const t = useTranslations("guided");
  // Chat features use the Settings page's own labels, so both read the same.
  const tp = useTranslations("pipeline");
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
    vision: draft.ingestion.vision_instance_id ?? "",
  });
  const suggested = () =>
    [t(docs ? "prompt.docs" : "prompt.general"), tasks ? t("prompt.tasks") : ""]
      .filter(Boolean)
      .join(" ");
  // The suggestion follows the answers until the admin writes their own prompt; a saved
  // suggestion still counts as one.
  const suggestions = [true, false].flatMap((d) =>
    [false, true].map((k) =>
      [t(d ? "prompt.docs" : "prompt.general"), k ? t("prompt.tasks") : ""]
        .filter(Boolean)
        .join(" "),
    ),
  );
  const [prompt, setPrompt] = useState(
    suggestions.includes(draft.generation.system_prompt) ? "" : draft.generation.system_prompt,
  );
  const shownPrompt = prompt || suggested();
  // General chat: models people may switch between, and the thinking switch.
  const [choices, setChoices] = useState<string[]>(draft.chat?.llm_instance_ids ?? []);
  const [thinkingSwitch, setThinkingSwitch] = useState(Boolean(draft.chat?.thinking));
  const [attachments, setAttachments] = useState(draft.chat?.attachments ?? true);
  const [webSearch, setWebSearch] = useState(draft.chat?.web_search_instance_id ?? "");
  const [code, setCode] = useState(draft.chat?.code_instance_id ?? "");
  // What the data rule should allow as well, ticked here by governance editors.
  const [allowNoDocs, setAllowNoDocs] = useState(false);
  const [allowExternal, setAllowExternal] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Providers added in another tab show up when the admin comes back.
  useRefreshOnFocus();

  const of = (cap: string) => providers.filter((p) => p.capability === cap);
  // General chat: models people may switch to besides the default one.
  const others = of("llm").filter((p) => p.id !== picked.llm);
  const needed: { key: keyof typeof picked; cap: string; optional?: boolean }[] = [
    { key: "llm", cap: "llm" },
    ...(tasks ? [{ key: "agent" as const, cap: "llm", optional: true }] : []),
    ...(docs
      ? [
          { key: "embedding" as const, cap: "embedding" },
          { key: "parser" as const, cap: "parser" },
          { key: "store" as const, cap: "vector_store" },
          ...(rerank ? [{ key: "reranker" as const, cap: "reranker" }] : []),
          // Only offered once a vision model is set up; documents work without one.
          ...(of("vision").length
            ? [{ key: "vision" as const, cap: "vision", optional: true }]
            : []),
        ]
      : []),
  ];
  const external = [
    ...needed.map((n) => picked[n.key]),
    ...(docs ? [] : choices.filter((id) => id !== picked.llm)),
    webSearch,
  ]
    .map((id) => providers.find((p) => p.id === id))
    .filter((p): p is Provider => !!p && p.hosting === "external");
  const blocked = [...new Map(external.map((p) => [p.id, p])).values()].filter(
    (p) => !rule.allowed_external_instance_ids.includes(p.id),
  );

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
      next_.ingestion.vision_instance_id = ref(picked.vision);
      // Choosing a vision model is choosing to have pictures described.
      if (picked.vision) next_.ingestion.describe_images = true;
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
      // Settings the questions don't ask about stay as they are.
      ...next_.chat,
      attachments,
      web_search_instance_id: ref(webSearch),
      code_instance_id: ref(code),
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
      const noDocs = !docs && allowNoDocs && !rule.allow_no_documents;
      const extra = allowExternal.filter((id) => blocked.some((p) => p.id === id));
      if (canAllow && (noDocs || extra.length)) {
        await api(`/v1/admin/chatbots/${botId}/governance`, {
          method: "PUT",
          body: JSON.stringify({
            chat_retention_days: rule.chat_retention_days,
            trace_retention_days: rule.trace_retention_days,
            allowed_external_instance_ids: [...rule.allowed_external_instance_ids, ...extra],
            allowed_external_mcp_server_ids: rule.allowed_external_mcp_server_ids,
            allow_byok: rule.allow_byok,
            allow_external_traces: rule.allow_external_traces,
            allow_no_documents: rule.allow_no_documents || noDocs,
            mask_pii_before_external: rule.mask_pii_before_external,
          }),
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
        {docs ? null : rule.allow_no_documents ? (
          <p className="m-0 flex items-center gap-2 text-sm text-fg-secondary">
            <CircleCheck aria-hidden className="size-4 shrink-0 text-green" />
            {t("rules.noDocsAllowed")}
          </p>
        ) : canAllow ? (
          <div role="note" className={ruleNote}>
            <p className="m-0">{t("general.rule")}</p>
            <label className={ruleCheck}>
              <input
                type="checkbox"
                checked={allowNoDocs}
                onChange={(e) => setAllowNoDocs(e.target.checked)}
                className="mt-0.5"
              />
              <span className="flex flex-col">
                {t("rules.allowNoDocs")}
                <span className="text-xs font-normal text-fg-muted">{t("rules.allowHint")}</span>
              </span>
            </label>
          </div>
        ) : (
          <p role="note" className={ruleBlocked}>
            {t("rules.noDocsAsk")}
          </p>
        )}
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
          <label className={card(thinkingSwitch)}>
            <input
              type="checkbox"
              checked={thinkingSwitch}
              onChange={(e) => setThinkingSwitch(e.target.checked)}
            />
            <span className="flex flex-col">
              <span className="font-medium">{tp("f.thinking.label")}</span>
              <span className="text-xs text-fg-muted">{tp("f.thinking.hint")}</span>
            </span>
          </label>
        ) : null}
        <label className={card(attachments)}>
          <input
            type="checkbox"
            checked={attachments}
            onChange={(e) => setAttachments(e.target.checked)}
          />
          <span className="flex flex-col">
            <span className="font-medium">{tp("f.attachments.label")}</span>
            <span className="text-xs text-fg-muted">{tp("f.attachments.hint")}</span>
          </span>
        </label>
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
        <p className="m-0 text-xs text-fg-muted">
          {t.rich("providersHint", {
            link: (c) => (
              <NewTabLink href="/admin/providers" className="inline-flex items-center gap-1">
                {c}
              </NewTabLink>
            ),
          })}
        </p>
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
                    <option value="">
                      {n.key === "vision"
                        ? t("noVision")
                        : n.optional
                          ? t("sameAsAnswers")
                          : t("choose")}
                    </option>
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
                    <NewTabLink
                      href="/admin/providers/new"
                      className="flex items-center gap-1 text-sm"
                    >
                      {t("addProvider")}
                    </NewTabLink>
                  </span>
                )}
                <span className="text-xs font-normal text-fg-muted">{t(`needHint.${n.key}`)}</span>
              </label>
            );
          })}
        </div>
        {!docs && picked.llm && others.length ? (
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
            <legend className="p-0 text-[13px] font-medium">
              {tp("f.llm_instance_ids.label")}
            </legend>
            <span className="text-xs text-fg-muted">{tp("f.llm_instance_ids.hint")}</span>
            <span className="mt-1 flex flex-wrap gap-x-5 gap-y-1.5">
              {others.map((p) => (
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
            </span>
          </fieldset>
        ) : null}
        {of("web_search").length || of("code_interpreter").length ? (
          <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
            {(
              [
                ["web_search", "web_search_instance_id", webSearch, setWebSearch],
                ["code_interpreter", "code_instance_id", code, setCode],
              ] as const
            ).map(([cap, name, value, set]) =>
              of(cap).length ? (
                <label key={cap} className={field}>
                  {tp(`f.${name}.label`)}
                  <select value={value} onChange={(e) => set(e.target.value)} className={control}>
                    <option value="">{tp("none")}</option>
                    {of(cap).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                        {p.hosting === "external" ? ` · ${t("external")}` : ""}
                      </option>
                    ))}
                  </select>
                  <span className="text-xs font-normal text-fg-muted">{tp(`f.${name}.hint`)}</span>
                </label>
              ) : null,
            )}
          </div>
        ) : null}
        {blocked.length ? (
          <div role="note" className={canAllow ? ruleNote : ruleBlocked}>
            {canAllow ? (
              <>
                <p className="m-0">
                  {t("rules.external", { names: blocked.map((p) => p.name).join(", ") })}
                </p>
                {blocked.map((p) => (
                  <label key={p.id} className={ruleCheck}>
                    <input
                      type="checkbox"
                      checked={allowExternal.includes(p.id)}
                      onChange={(e) =>
                        setAllowExternal((l) =>
                          e.target.checked ? [...l, p.id] : l.filter((x) => x !== p.id),
                        )
                      }
                      className="mt-0.5"
                    />
                    {t("rules.allowExternal", { name: p.name })}
                  </label>
                ))}
                <span className="text-xs text-fg-muted">{t("rules.allowHint")}</span>
              </>
            ) : (
              <p className="m-0">
                {t("rules.externalAsk", { names: blocked.map((p) => p.name).join(", ") })}
              </p>
            )}
          </div>
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
