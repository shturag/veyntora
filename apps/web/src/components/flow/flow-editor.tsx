"use client";

import "@xyflow/react/dist/style.css";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  addEdge,
  type NodeProps,
  type Connection,
  type Edge,
  type Node,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/chat";

const TYPES = [
  "input",
  "router",
  "retriever",
  "reranker",
  "llm",
  "agent_llm",
  "mcp_tool",
  "condition",
  "guardrail",
  "human_approval",
  "output",
] as const;
type StepType = (typeof TYPES)[number];
type Config = Record<string, unknown>;
type StepData = {
  label: string;
  type: StepType;
  config: Config;
  provider_instance_id: string | null;
};
type FlowNode = Node<StepData>;
type FlowEdge = Edge<{ label: string }>;
type FlowSpec = {
  custom?: boolean;
  nodes: {
    id: string;
    type: StepType;
    label?: string;
    x?: number;
    y?: number;
    config?: Config;
    provider_instance_id?: string | null;
  }[];
  edges: { source: string; target: string; label?: string }[];
};
const LABELS = ["", "fast", "agent", "yes", "no", "pass", "fail", "rejected"] as const;
const control =
  "h-9 w-full rounded-md border border-line-strong bg-surface px-2 text-sm font-normal";

/** One step on the canvas: its type and name, with connection handles. */
function StepNode({ data }: NodeProps<FlowNode>) {
  const t = useTranslations("flow");
  return (
    <div className="rounded-md border border-line-strong bg-surface px-3 py-2 text-xs shadow-sm">
      {data.type !== "input" ? <Handle type="target" position={Position.Top} /> : null}
      <div className="font-semibold">{t(`types.${data.type}`)}</div>
      <div className="text-fg-muted">{data.label}</div>
      {data.type !== "output" ? <Handle type="source" position={Position.Bottom} /> : null}
    </div>
  );
}

// Stable across renders (React Flow warns and re-mounts nodes otherwise).
const NODE_TYPES = { step: StepNode };

function toNodes(flow: FlowSpec): FlowNode[] {
  return flow.nodes.map((n, i) => ({
    id: n.id,
    type: "step",
    position: { x: n.x ?? 40 + (i % 4) * 220, y: n.y ?? 40 + Math.floor(i / 4) * 140 },
    data: {
      label: n.label || n.id,
      type: n.type,
      config: n.config ?? {},
      provider_instance_id: n.provider_instance_id ?? null,
    },
  }));
}

function toEdges(flow: FlowSpec): FlowEdge[] {
  return flow.edges.map((e, i) => ({
    id: `e${i}-${e.source}-${e.target}`,
    source: e.source,
    target: e.target,
    label: e.label || undefined,
    data: { label: e.label ?? "" },
  }));
}

/** The chatbot's flow on a canvas (prototype: BotFlow.html), with a keyboard-friendly list. */
export function FlowEditor({
  botId,
  version,
  spec,
  llms,
  tools,
  problems,
  canEdit,
}: {
  botId: string;
  version: number;
  spec: PipelineSpec;
  llms: { id: string; name: string }[];
  tools: { id: string; name: string; server: string; access: string }[];
  problems: string[];
  canEdit: boolean;
}) {
  const t = useTranslations("flow");
  const router = useRouter();
  const flow = (spec as unknown as { flow: FlowSpec }).flow;
  const [custom, setCustom] = useState(Boolean(flow.custom));
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(toNodes(flow));
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>(toEdges(flow));
  const [selected, setSelected] = useState<string | null>(null);
  const [edgeSel, setEdgeSel] = useState<string | null>(null);
  const [link, setLink] = useState({ from: "", to: "", label: "" });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const node = nodes.find((n) => n.id === selected);
  const edge = edges.find((e) => e.id === edgeSel);

  function addStep(type: StepType) {
    let n = 1;
    while (nodes.some((x) => x.id === `${type}_${n}`)) n += 1;
    const id = `${type}_${n}`;
    setNodes((list) => [
      ...list,
      {
        id,
        type: "step",
        position: { x: 80 + list.length * 24, y: 80 + list.length * 24 },
        data: { label: t(`types.${type}`), type, config: {}, provider_instance_id: null },
      },
    ]);
    setSelected(id);
    setEdgeSel(null);
  }

  function connect(c: Connection | { source: string; target: string }, label = "") {
    if (!c.source || !c.target || c.source === c.target) return;
    setEdges((list) =>
      addEdge(
        {
          id: `e${Date.now()}-${c.source}-${c.target}`,
          source: c.source,
          target: c.target,
          label: label || undefined,
          data: { label },
        },
        list,
      ),
    );
  }

  const patch = (data: Partial<StepData>) =>
    setNodes((list) =>
      list.map((n) => (n.id === selected ? { ...n, data: { ...n.data, ...data } } : n)),
    );
  const patchConfig = (key: string, value: unknown) =>
    node && patch({ config: { ...node.data.config, [key]: value } });

  async function save() {
    const next = structuredClone(spec) as unknown as { flow: FlowSpec };
    next.flow = {
      custom,
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.data.type,
        label: n.data.label,
        x: Math.round(n.position.x),
        y: Math.round(n.position.y),
        config: n.data.config,
        provider_instance_id: n.data.provider_instance_id,
      })),
      edges: edges.map((e) => ({ source: e.source, target: e.target, label: e.data?.label ?? "" })),
    };
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/pipeline/draft`, {
        method: "PUT",
        headers: { "If-Match": String(version) },
        body: JSON.stringify({ spec: next, change_note: "flow edited" }),
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

  const cfg = node?.data.config ?? {};
  const str = (k: string) =>
    typeof cfg[k] === "string" || typeof cfg[k] === "number" ? String(cfg[k]) : "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/admin/pipelines/${botId}`} className="text-sm underline">
          {t("formView")}
        </Link>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={custom}
            disabled={!canEdit}
            onChange={(e) => setCustom(e.target.checked)}
          />
          {t("runThis")}
        </label>
        <div className="flex items-center gap-3">
          {message ? (
            <span
              role={message.ok ? "status" : "alert"}
              className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
            >
              {message.text}
            </span>
          ) : null}
          {canEdit ? (
            <Button variant="primary" disabled={busy} onClick={save}>
              {t("save")}
            </Button>
          ) : null}
        </div>
      </div>
      <p className="m-0 text-xs text-fg-muted">{custom ? t("customNote") : t("standardNote")}</p>
      <section
        aria-labelledby="flow-checks"
        className={`rounded-md px-3 py-2 text-sm ${problems.length ? "bg-amber-soft" : "bg-green-soft"}`}
      >
        <h2 id="flow-checks" className="m-0 text-sm font-semibold">
          {problems.length ? t("problems") : t("valid")}
        </h2>
        {problems.length ? (
          <ul className="m-0 mt-1 pl-5">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
      </section>
      <div className="grid grid-cols-[180px_minmax(0,1fr)_300px] items-start gap-4 max-[1100px]:grid-cols-1">
        <nav aria-label={t("palette")} className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-fg-muted uppercase">{t("addStep")}</span>
          {TYPES.filter((x) => x !== "input").map((type) => (
            <Button key={type} size="sm" disabled={!canEdit} onClick={() => addStep(type)}>
              + {t(`types.${type}`)}
            </Button>
          ))}
        </nav>
        <div
          className="h-[560px] rounded-lg border border-line bg-surface"
          aria-label={t("canvas")}
          role="region"
        >
          <ReactFlow
            nodes={nodes}
            nodeTypes={NODE_TYPES}
            edges={edges}
            onNodesChange={canEdit ? onNodesChange : undefined}
            onEdgesChange={canEdit ? onEdgesChange : undefined}
            onConnect={canEdit ? (c) => connect(c) : undefined}
            onNodeClick={(_, n) => {
              setSelected(n.id);
              setEdgeSel(null);
            }}
            onEdgeClick={(_, e) => {
              setEdgeSel(e.id);
              setSelected(null);
            }}
            nodesDraggable={canEdit}
            fitView
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <aside
          aria-label={t("details")}
          className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        >
          <label className="flex flex-col gap-1 text-[13px] font-medium">
            {t("step")}
            <select
              value={selected ?? ""}
              onChange={(e) => {
                setSelected(e.target.value || null);
                setEdgeSel(null);
              }}
              className={control}
            >
              <option value="">{t("chooseStep")}</option>
              {nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {t(`types.${n.data.type}`)}: {n.data.label}
                </option>
              ))}
            </select>
          </label>
          {node ? (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1 text-[13px] font-medium">
                {t("label")}
                <input
                  value={node.data.label}
                  disabled={!canEdit}
                  onChange={(e) => patch({ label: e.target.value })}
                  className={control}
                />
              </label>
              {node.data.type === "retriever" ? (
                <>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.top_k")}
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={str("top_k")}
                      disabled={!canEdit}
                      onChange={(e) => patchConfig("top_k", Number(e.target.value) || undefined)}
                      className={control}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.search_type")}
                    <select
                      value={str("search_type")}
                      disabled={!canEdit}
                      onChange={(e) => patchConfig("search_type", e.target.value || undefined)}
                      className={control}
                    >
                      <option value="">{t("asPipeline")}</option>
                      <option value="hybrid">hybrid</option>
                      <option value="dense">dense</option>
                      <option value="sparse">sparse</option>
                    </select>
                  </label>
                </>
              ) : null}
              {node.data.type === "reranker" ? (
                <>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.top_n")}
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={str("top_n")}
                      disabled={!canEdit}
                      onChange={(e) => patchConfig("top_n", Number(e.target.value) || undefined)}
                      className={control}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.min_score")}
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={str("min_score")}
                      disabled={!canEdit}
                      onChange={(e) =>
                        patchConfig(
                          "min_score",
                          e.target.value === "" ? undefined : Number(e.target.value),
                        )
                      }
                      className={control}
                    />
                  </label>
                </>
              ) : null}
              {node.data.type === "llm" ? (
                <>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.model")}
                    <select
                      value={node.data.provider_instance_id ?? ""}
                      disabled={!canEdit}
                      onChange={(e) => patch({ provider_instance_id: e.target.value || null })}
                      className={control}
                    >
                      <option value="">{t("asPipeline")}</option>
                      {llms.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.system_prompt")}
                    <textarea
                      rows={4}
                      value={str("system_prompt")}
                      disabled={!canEdit}
                      onChange={(e) => patchConfig("system_prompt", e.target.value || undefined)}
                      className="rounded-md border border-line-strong bg-surface p-2 text-sm font-normal"
                    />
                  </label>
                </>
              ) : null}
              {node.data.type === "mcp_tool" ? (
                <>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.tool")}
                    <select
                      value={str("tool_id")}
                      disabled={!canEdit}
                      onChange={(e) => patchConfig("tool_id", e.target.value || undefined)}
                      className={control}
                    >
                      <option value="">{t("toolbox")}</option>
                      {tools.map((x) => (
                        <option key={x.id} value={x.id}>
                          {x.server}: {x.name} ({x.access})
                        </option>
                      ))}
                    </select>
                  </label>
                  {str("tool_id") ? (
                    <label className="flex flex-col gap-1 text-[13px] font-medium">
                      {t("cfg.arguments")}
                      <textarea
                        rows={3}
                        defaultValue={JSON.stringify(cfg.arguments ?? {}, null, 1)}
                        disabled={!canEdit}
                        onBlur={(e) => {
                          try {
                            patchConfig("arguments", JSON.parse(e.target.value || "{}"));
                          } catch {
                            setMessage({ ok: false, text: t("badJson") });
                          }
                        }}
                        className="rounded-md border border-line-strong bg-surface p-2 font-mono text-xs font-normal"
                      />
                      <span className="text-xs font-normal text-fg-muted">{t("argsHint")}</span>
                    </label>
                  ) : (
                    <fieldset className="m-0 flex flex-col gap-1 border-0 p-0 text-sm">
                      <legend className="mb-1 p-0 text-[13px] font-medium">{t("cfg.tools")}</legend>
                      {tools.map((x) => {
                        const ids = (cfg.tool_ids as string[] | undefined) ?? [];
                        return (
                          <label key={x.id} className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={ids.includes(x.id)}
                              disabled={!canEdit}
                              onChange={(e) =>
                                patchConfig(
                                  "tool_ids",
                                  e.target.checked ? [...ids, x.id] : ids.filter((i) => i !== x.id),
                                )
                              }
                            />
                            {x.server}: {x.name}
                          </label>
                        );
                      })}
                      <span className="text-xs text-fg-muted">{t("toolboxHint")}</span>
                    </fieldset>
                  )}
                </>
              ) : null}
              {node.data.type === "condition" ? (
                <>
                  <label className="flex flex-col gap-1 text-[13px] font-medium">
                    {t("cfg.test")}
                    <select
                      value={str("test")}
                      disabled={!canEdit}
                      onChange={(e) => patchConfig("test", e.target.value || undefined)}
                      className={control}
                    >
                      <option value="">{t("choose")}</option>
                      {["no_sources", "grounded_below", "question_matches"].map((x) => (
                        <option key={x} value={x}>
                          {t(`tests.${x}` as "tests.no_sources")}
                        </option>
                      ))}
                    </select>
                  </label>
                  {str("test") && str("test") !== "no_sources" ? (
                    <label className="flex flex-col gap-1 text-[13px] font-medium">
                      {t("cfg.value")}
                      <input
                        value={str("value")}
                        disabled={!canEdit}
                        onChange={(e) => patchConfig("value", e.target.value)}
                        className={control}
                      />
                    </label>
                  ) : null}
                </>
              ) : null}
              {node.data.type === "guardrail" ? (
                <label className="flex flex-col gap-1 text-[13px] font-medium">
                  {t("cfg.check")}
                  <select
                    value={str("check") || "grounded"}
                    disabled={!canEdit}
                    onChange={(e) => patchConfig("check", e.target.value)}
                    className={control}
                  >
                    {["grounded", "input", "output"].map((x) => (
                      <option key={x} value={x}>
                        {t(`checks.${x}` as "checks.grounded")}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <p className="m-0 text-xs text-fg-muted">{t(`help.${node.data.type}`)}</p>
              {canEdit && node.data.type !== "input" ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setNodes((l) => l.filter((n) => n.id !== node.id));
                    setEdges((l) => l.filter((e) => e.source !== node.id && e.target !== node.id));
                    setSelected(null);
                  }}
                >
                  {t("removeStep")}
                </Button>
              ) : null}
            </div>
          ) : null}
          {edge ? (
            <div className="flex flex-col gap-2 border-t border-line pt-3">
              <span className="text-[13px] font-medium">
                {t("connection", { from: edge.source, to: edge.target })}
              </span>
              <label className="flex flex-col gap-1 text-[13px] font-medium">
                {t("branch")}
                <select
                  value={edge.data?.label ?? ""}
                  disabled={!canEdit}
                  onChange={(e) =>
                    setEdges((l) =>
                      l.map((x) =>
                        x.id === edge.id
                          ? {
                              ...x,
                              label: e.target.value || undefined,
                              data: { label: e.target.value },
                            }
                          : x,
                      ),
                    )
                  }
                  className={control}
                >
                  {LABELS.map((x) => (
                    <option key={x} value={x}>
                      {x ? t(`branches.${x}` as "branches.fast") : t("always")}
                    </option>
                  ))}
                </select>
              </label>
              {canEdit ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEdges((l) => l.filter((x) => x.id !== edge.id));
                    setEdgeSel(null);
                  }}
                >
                  {t("removeConnection")}
                </Button>
              ) : null}
            </div>
          ) : null}
          {canEdit ? (
            <form
              aria-label={t("connectTitle")}
              onSubmit={(e) => {
                e.preventDefault();
                connect({ source: link.from, target: link.to }, link.label);
              }}
              className="flex flex-col gap-2 border-t border-line pt-3"
            >
              <span className="text-[13px] font-medium">{t("connectTitle")}</span>
              {(["from", "to"] as const).map((k) => (
                <label key={k} className="flex flex-col gap-1 text-[13px] font-medium">
                  {t(k)}
                  <select
                    value={link[k]}
                    onChange={(e) => setLink({ ...link, [k]: e.target.value })}
                    className={control}
                  >
                    <option value="">{t("chooseStep")}</option>
                    {nodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.data.label}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              <label className="flex flex-col gap-1 text-[13px] font-medium">
                {t("branch")}
                <select
                  value={link.label}
                  onChange={(e) => setLink({ ...link, label: e.target.value })}
                  className={control}
                >
                  {LABELS.map((x) => (
                    <option key={x} value={x}>
                      {x ? t(`branches.${x}` as "branches.fast") : t("always")}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" size="sm" disabled={!link.from || !link.to}>
                {t("connect")}
              </Button>
            </form>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
