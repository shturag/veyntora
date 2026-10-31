"use client";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

type Provider = { id: string; name: string; capability: string; hosting: string };
type Mode = "auto" | "fast" | "agent";
const MODES: Mode[] = ["auto", "fast", "agent"];
type Ref = string | null | undefined;
// The draft as the API returns it: every section is present (defaults filled in).
type Core = {
  ingestion: { parser_instance_id?: Ref; embedding_instance_id?: Ref };
  retrieval: { embedding_instance_id?: Ref; vector_store_instance_id?: Ref };
  generation: { llm_instance_id?: Ref };
  rerank: { enabled?: boolean; reranker_instance_id?: Ref };
  router: { allowed_modes: Mode[]; default_mode: Mode };
};
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

/** The providers a chatbot needs to answer, and its modes; every other setting keeps its
 *  default and is changed on the Pipeline pages. */
export function PipelineCore({
  botId,
  version,
  spec,
  providers,
  next,
}: {
  botId: string;
  version: number;
  spec: PipelineSpec;
  providers: Provider[];
  next: string;
}) {
  const core = spec as unknown as Core;
  const t = useTranslations("bots");
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const of = (cap: string) => providers.filter((p) => p.capability === cap);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const get = (k: string) => String(f.get(k) || "") || null;
    const draft = structuredClone(core);
    const embedding = get("embedding");
    draft.ingestion.parser_instance_id = get("parser");
    draft.ingestion.embedding_instance_id = embedding;
    draft.retrieval.embedding_instance_id = embedding;
    draft.retrieval.vector_store_instance_id = get("store");
    draft.generation.llm_instance_id = get("llm");
    const reranker = get("reranker");
    draft.rerank.reranker_instance_id = reranker;
    draft.rerank.enabled = Boolean(reranker);
    const modes = f.getAll("modes").map(String) as Mode[];
    const fallback = modes[0] ?? "fast";
    draft.router.allowed_modes = modes.length ? modes : ["fast"];
    draft.router.default_mode = modes.includes(String(f.get("default")) as Mode)
      ? (String(f.get("default")) as Mode)
      : fallback;
    setBusy(true);
    setError(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/pipeline/draft`, {
        method: "PUT",
        headers: { "If-Match": String(version) },
        body: JSON.stringify({ spec: draft, change_note: "set up in the new chatbot wizard" }),
      });
      router.push(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  const select = (
    name: string,
    cap: string,
    value: string | null | undefined,
    optional = false,
  ) => (
    <label className="flex flex-col gap-1 text-[13px] font-medium">
      {t(`core.${name}` as "core.llm")}
      <select name={name} defaultValue={value ?? ""} required={!optional} className={control}>
        <option value="">{optional ? t("none") : t("choose")}</option>
        {of(cap).map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
            {p.hosting === "external" ? ` · ${t("external")}` : ""}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <form
      aria-label={t("wizardPipelineForm")}
      onSubmit={save}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        {select("parser", "parser", core.ingestion.parser_instance_id)}
        {select("embedding", "embedding", core.ingestion.embedding_instance_id)}
        {select("store", "vector_store", core.retrieval.vector_store_instance_id)}
        {select("llm", "llm", core.generation.llm_instance_id)}
        {select(
          "reranker",
          "reranker",
          core.rerank.enabled ? core.rerank.reranker_instance_id : null,
          true,
        )}
      </div>
      <fieldset className="m-0 flex flex-wrap items-center gap-4 border-0 p-0">
        <legend className="mb-1 p-0 text-[13px] font-medium">{t("modesAllowed")}</legend>
        {MODES.map((m) => (
          <label key={m} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="modes"
              value={m}
              defaultChecked={core.router.allowed_modes.includes(m)}
            />
            {t(`modes.${m}`)}
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          {t("defaultMode")}
          <select name="default" defaultValue={core.router.default_mode} className={control}>
            {MODES.map((m) => (
              <option key={m} value={m}>
                {t(`modes.${m}`)}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      {providers.length === 0 ? (
        <p className="m-0 text-sm text-fg-muted">{t("noProviders")}</p>
      ) : null}
      <p className="m-0 text-xs text-fg-muted">{t("externalNote")}</p>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={busy}>
          {t("saveContinue")}
        </Button>
      </div>
    </form>
  );
}
