"use client";

import "@xyflow/react/dist/style.css";

import type { PipelineSpec } from "@veyntora/spec";
import { Button } from "@veyntora/ui";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  Bot,
  CircleAlert,
  GitBranch,
  ListOrdered,
  type LucideIcon,
  MessageSquare,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Split,
  UserCheck,
  Wrench,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { PublishChecklist } from "@/components/pipeline/publish-checklist";
import { api } from "@/lib/chat";
import { COL_W, ROW_H, layoutFlow, needsLayout } from "@/lib/flow-layout";

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
  /** One line under the name: what the step is set to do. */
  summary: string;
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
const field = "flex flex-col gap-1 text-[13px] font-medium";

/** How each kind of step looks: icon and colour by what it does (categorical, fixed order). */
const KIND: Record<
  StepType,
  { icon: LucideIcon; group: "start" | "find" | "answer" | "act" | "check"; tone: string }
> = {
  input: { icon: MessageSquare, group: "start", tone: "text-fg-secondary bg-sunken" },
  router: { icon: Split, group: "start", tone: "text-series-7 bg-series-7/10" },
  retriever: { icon: Search, group: "find", tone: "text-series-1 bg-series-1/10" },
  reranker: { icon: ListOrdered, group: "find", tone: "text-series-1 bg-series-1/10" },
  llm: { icon: Sparkles, group: "answer", tone: "text-series-3 bg-series-3/10" },
  agent_llm: { icon: Bot, group: "act", tone: "text-series-2 bg-series-2/10" },
  mcp_tool: { icon: Wrench, group: "act", tone: "text-series-2 bg-series-2/10" },
  condition: { icon: GitBranch, group: "check", tone: "text-series-5 bg-series-5/10" },
  guardrail: { icon: ShieldCheck, group: "check", tone: "text-series-5 bg-series-5/10" },
  human_approval: { icon: UserCheck, group: "check", tone: "text-series-5 bg-series-5/10" },
  output: { icon: Send, group: "answer", tone: "text-fg-secondary bg-sunken" },
};
const GROUPS = ["start", "find", "answer", "act", "check"] as const;

/** One step on the canvas: icon, name, what it is set to, and connection points. */
function StepNode({ data, selected }: NodeProps<FlowNode>) {
  const t = useTranslations("flow");
  const { icon: Icon, tone } = KIND[data.type];
  return (
    <div
      className={`flex w-[230px] items-start gap-2.5 rounded-lg border bg-surface px-3 py-2.5 shadow-sm transition-shadow ${
        selected ? "border-accent ring-2 ring-accent/30" : "border-line-strong hover:shadow-md"
      }`}
    >
      {data.type !== "input" ? (
        <Handle type="target" position={Position.Top} className="!size-2.5 !bg-fg-muted" />
      ) : null}
      <span className={`grid size-8 shrink-0 place-items-center rounded-md ${tone}`}>
        <Icon aria-hidden className="size-4" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="text-[10px] font-semibold tracking-wide text-fg-muted uppercase">
          {t(`types.${data.type}`)}
        </span>
        <span className="truncate text-[13px] font-semibold text-fg">{data.label}</span>
        <span className="truncate text-[11px] text-fg-muted" title={data.summary}>
          {data.summary}
        </span>
      </span>
      {data.type !== "output" ? (
        <Handle type="source" position={Position.Bottom} className="!size-2.5 !bg-fg-muted" />
      ) : null}
      {/* For drawing only: loops with a step beside this one, or back up the flow. */}
      <Handle
        id="l"
        type="target"
        position={Position.Left}
        isConnectable={false}
        className="!opacity-0"
      />
      <Handle
        id="r"
        type="source"
        position={Position.Right}
        isConnectable={false}
        className="!opacity-0"
      />
      <Handle
        id="ri"
        type="target"
        position={Position.Right}
        isConnectable={false}
        className="!opacity-0"
      />
    </div>
  );
}

// Stable across renders (React Flow warns and re-mounts nodes otherwise).
const NODE_TYPES = { step: StepNode };

/** The chatbot's flow on a canvas (prototype: BotFlow.html), with a keyboard-friendly panel. */
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
  const { resolvedTheme } = useTheme();
  const flow = (spec as unknown as { flow: FlowSpec }).flow;

  const summarise = (type: StepType, config: Config, provider: string | null): string => {
    const n = (k: string) => (typeof config[k] === "number" ? (config[k] as number) : null);
    switch (type) {
      case "llm":
        return llms.find((l) => l.id === provider)?.name ?? t("sum.pipelineModel");
      case "agent_llm":
        return t("sum.pipelineModel");
      case "retriever":
        return n("top_k") ? t("sum.topK", { n: n("top_k")! }) : t("sum.pipeline");
      case "reranker":
        return n("top_n") ? t("sum.keep", { n: n("top_n")! }) : t("sum.pipeline");
      case "mcp_tool": {
        const one = tools.find((x) => x.id === config.tool_id);
        if (one) return one.name;
        const ids = (config.tool_ids as string[] | undefined) ?? [];
        return t("sum.toolbox", { count: ids.length });
      }
      case "condition":
        return typeof config.test === "string"
          ? t(`tests.${config.test}` as "tests.no_sources")
          : t("sum.noTest");
      case "guardrail":
        return t(`checks.${(config.check as string) || "grounded"}` as "checks.grounded");
      default:
        return t(`sum.${type}` as "sum.input");
    }
  };

  const initial = useMemo(() => {
    const saved = flow.nodes;
    const auto = needsLayout(saved) ? layoutFlow(saved, flow.edges) : null;
    const nodes: FlowNode[] = saved.map((n) => ({
      id: n.id,
      type: "step",
      position: auto?.[n.id] ?? { x: n.x ?? 0, y: n.y ?? 0 },
      data: {
        label: n.label || n.id,
        type: n.type,
        config: n.config ?? {},
        provider_instance_id: n.provider_instance_id ?? null,
        summary: summarise(n.type, n.config ?? {}, n.provider_instance_id ?? null),
      },
    }));
    const edges: FlowEdge[] = flow.edges.map((e, i) =>
      edgeOf(`e${i}`, e.source, e.target, e.label ?? ""),
    );
    return { nodes, edges };
    // Only on first render: later changes live in state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function edgeOf(id: string, source: string, target: string, label: string): FlowEdge {
    return {
      id,
      source,
      target,
      type: "smoothstep",
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      label: label ? t(`branches.${label}` as "branches.fast") : undefined,
      labelBgPadding: [6, 3],
      labelBgBorderRadius: 999,
      data: { label },
    };
  }

  const [custom, setCustom] = useState(Boolean(flow.custom));
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>(initial.edges);
  const [selected, setSelected] = useState<string | null>(null);
  const [edgeSel, setEdgeSel] = useState<string | null>(null);
  const [link, setLink] = useState({ from: "", to: "", label: "" });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const rf = useRef<ReactFlowInstance<FlowNode, FlowEdge> | null>(null);
  const node = nodes.find((n) => n.id === selected);
  const edge = edges.find((e) => e.id === edgeSel);
  // The standard pipeline runs whatever the forms say: its picture is for reading.
  const editable = canEdit && custom;
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.data.label ?? id;
  // Two steps that call each other side by side (an agent and its tools) get one two-way
  // arrow; any other connection back up the flow is a dashed curve along the right side.
  const shown = useMemo(() => {
    const pos = new Map(nodes.map((n) => [n.id, n.position]));
    const has = new Set(edges.map((e) => `${e.source}>${e.target}`));
    return edges.flatMap((e): FlowEdge[] => {
      const s = pos.get(e.source);
      const d = pos.get(e.target);
      if (!s || !d) return [e];
      if (has.has(`${e.target}>${e.source}`) && Math.abs(s.y - d.y) < 20) {
        if (s.x > d.x) return [];
        return [
          {
            ...e,
            sourceHandle: "r",
            targetHandle: "l",
            type: "straight",
            markerStart: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          },
        ];
      }
      if (s.y > d.y + 20) {
        return [
          {
            ...e,
            sourceHandle: "r",
            targetHandle: "ri",
            type: "default",
            style: { strokeDasharray: "5 4" },
          },
        ];
      }
      return [e];
    });
  }, [nodes, edges]);

  const snapshot = (c: boolean, ns: FlowNode[], es: FlowEdge[]) =>
    JSON.stringify([
      c,
      ns.map((n) => [n.id, n.data.label, n.data.config, n.data.provider_instance_id]),
      es.map((e) => [e.source, e.target, e.data?.label ?? ""]),
    ]);
  const [baseline, setBaseline] = useState(() =>
    snapshot(Boolean(flow.custom), initial.nodes, initial.edges),
  );
  const dirty = snapshot(custom, nodes, edges) !== baseline;

  function tidy() {
    const at = layoutFlow(nodes, edges);
    setNodes((list) => list.map((n) => ({ ...n, position: at[n.id] ?? n.position })));
    window.requestAnimationFrame(() => rf.current?.fitView({ padding: 0.15, duration: 300 }));
  }

  function addStep(type: StepType) {
    let n = 1;
    while (nodes.some((x) => x.id === `${type}_${n}`)) n += 1;
    const id = `${type}_${n}`;
    const after = node && node.data.type !== "output" ? node : null;
    const right = Math.max(0, ...nodes.map((x) => x.position.x));
    let position = after
      ? { x: after.position.x, y: after.position.y + ROW_H }
      : { x: right + COL_W, y: 0 };
    while (
      nodes.some(
        (x) => Math.abs(x.position.x - position.x) < 40 && Math.abs(x.position.y - position.y) < 40,
      )
    ) {
      position = { ...position, x: position.x + COL_W };
    }
    setNodes((list) => [
      ...list,
      {
        id,
        type: "step",
        position,
        selected: true,
        data: {
          label: t(`types.${type}`),
          type,
          config: {},
          provider_instance_id: null,
          summary: summarise(type, {}, null),
        },
      },
    ]);
    if (after) connect({ source: after.id, target: id });
    setSelected(id);
    setEdgeSel(null);
  }

  function connect(c: Connection | { source: string; target: string }, label = "") {
    if (!c.source || !c.target || c.source === c.target) return;
    setEdges((list) =>
      addEdge(edgeOf(`e${Date.now()}-${c.source}-${c.target}`, c.source, c.target, label), list),
    );
  }

  const patch = (data: Partial<StepData>) =>
    setNodes((list) =>
      list.map((n) => {
        if (n.id !== selected) return n;
        const next = { ...n.data, ...data };
        return {
          ...n,
          data: { ...next, summary: summarise(next.type, next.config, next.provider_instance_id) },
        };
      }),
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
      setBaseline(snapshot(custom, nodes, edges));
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
  const segment = (on: boolean) =>
    `rounded-md px-3 py-1.5 text-sm ${on ? "bg-surface font-medium text-fg shadow-sm" : "text-fg-secondary hover:text-fg"}`;

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar: how the chatbot runs, then the actions. */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div
            role="radiogroup"
            aria-label={t("modeLabel")}
            className="flex gap-0.5 rounded-lg bg-sunken p-1"
          >
            {([false, true] as const).map((c) => (
              <button
                key={String(c)}
                type="button"
                role="radio"
                aria-checked={custom === c}
                disabled={!canEdit}
                onClick={() => setCustom(c)}
                className={segment(custom === c)}
              >
                {c ? t("modes.custom") : t("modes.standard")}
              </button>
            ))}
          </div>
          <p className="m-0 max-w-[520px] text-xs text-fg-muted">
            {custom ? t("customNote") : t("standardNote")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {message ? (
            <span
              role={message.ok ? "status" : "alert"}
              className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
            >
              {message.text}
            </span>
          ) : dirty ? (
            <span className="flex items-center gap-1.5 text-sm text-amber">
              <span aria-hidden className="size-2 rounded-full bg-amber" />
              {t("unsaved")}
            </span>
          ) : null}
          <Button size="sm" onClick={tidy}>
            {t("tidy")}
          </Button>
          <Button asChild size="sm">
            <Link href={`/admin/pipelines/${botId}`}>{t("formView")}</Link>
          </Button>
          {canEdit ? (
            <Button size="sm" variant="primary" disabled={busy || !dirty} onClick={save}>
              {t("save")}
            </Button>
          ) : null}
        </div>
      </div>

      <PublishChecklist botId={botId} problems={problems} headingId="flow-checks" />

      <div className="grid grid-cols-[220px_minmax(0,1fr)_320px] items-start gap-4 max-[1200px]:grid-cols-[minmax(0,1fr)_300px] max-[860px]:grid-cols-1">
        <nav
          aria-label={t("palette")}
          className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-3 max-[1200px]:col-span-2 max-[860px]:col-span-1"
        >
          <div>
            <h2 className="m-0 text-sm font-semibold">{t("addStep")}</h2>
            <p className="m-0 text-xs text-fg-muted">{editable ? t("addHint") : t("addLocked")}</p>
          </div>
          {GROUPS.map((g) => {
            const types = TYPES.filter((x) => x !== "input" && KIND[x].group === g);
            if (!types.length) return null;
            return (
              <div key={g} className="flex flex-col gap-1">
                <span className="text-[11px] font-semibold tracking-wide text-fg-muted uppercase">
                  {t(`groups.${g}`)}
                </span>
                {types.map((type) => {
                  const { icon: Icon, tone } = KIND[type];
                  return (
                    <button
                      key={type}
                      type="button"
                      disabled={!editable}
                      onClick={() => addStep(type)}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-sunken disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span
                        className={`grid size-7 shrink-0 place-items-center rounded-md ${tone}`}
                      >
                        <Icon aria-hidden className="size-3.5" />
                      </span>
                      <span className="flex min-w-0 flex-col">
                        <span className="text-[13px] font-medium">{t(`types.${type}`)}</span>
                        <span className="truncate text-[11px] text-fg-muted">
                          {t(`desc.${type}`)}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <div
          className="h-[720px] overflow-hidden rounded-lg border border-line bg-ground"
          aria-label={t("canvas")}
          role="region"
        >
          <ReactFlow
            nodes={nodes}
            nodeTypes={NODE_TYPES}
            edges={shown}
            colorMode={
              resolvedTheme === "dark" ? "dark" : resolvedTheme === "light" ? "light" : "system"
            }
            onInit={(i) => {
              rf.current = i;
            }}
            onNodesChange={onNodesChange}
            onEdgesChange={editable ? onEdgesChange : undefined}
            onConnect={editable ? (c) => connect(c) : undefined}
            onNodeClick={(_, n) => {
              setSelected(n.id);
              setEdgeSel(null);
            }}
            onEdgeClick={(_, e) => {
              setEdgeSel(e.id);
              setSelected(null);
            }}
            onPaneClick={() => {
              setSelected(null);
              setEdgeSel(null);
            }}
            nodesConnectable={editable}
            deleteKeyCode={null}
            defaultEdgeOptions={{ type: "smoothstep" }}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.3}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} />
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        </div>

        <aside
          aria-label={t("details")}
          className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        >
          <label className={field}>
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
                  {n.data.label} ({t(`types.${n.data.type}`)})
                </option>
              ))}
            </select>
          </label>

          {!node && !edge ? (
            <p className="m-0 rounded-md bg-sunken px-3 py-2 text-xs text-fg-secondary">
              {editable ? t("inspectorEmpty") : t("inspectorReadOnly")}
            </p>
          ) : null}

          {node ? (
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2.5 border-b border-divider pb-3">
                {(() => {
                  const { icon: Icon, tone } = KIND[node.data.type];
                  return (
                    <span className={`grid size-9 place-items-center rounded-md ${tone}`}>
                      <Icon aria-hidden className="size-4" />
                    </span>
                  );
                })()}
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm font-semibold">{t(`types.${node.data.type}`)}</span>
                  <span className="text-xs text-fg-muted">{t(`desc.${node.data.type}`)}</span>
                </div>
              </div>
              <label className={field}>
                {t("label")}
                <input
                  value={node.data.label}
                  disabled={!editable}
                  onChange={(e) => patch({ label: e.target.value })}
                  className={control}
                />
              </label>
              {node.data.type === "retriever" ? (
                <>
                  <label className={field}>
                    {t("cfg.top_k")}
                    <input
                      type="number"
                      min={1}
                      max={200}
                      value={str("top_k")}
                      placeholder={t("asPipeline")}
                      disabled={!editable}
                      onChange={(e) => patchConfig("top_k", Number(e.target.value) || undefined)}
                      className={control}
                    />
                  </label>
                  <label className={field}>
                    {t("cfg.search_type")}
                    <select
                      value={str("search_type")}
                      disabled={!editable}
                      onChange={(e) => patchConfig("search_type", e.target.value || undefined)}
                      className={control}
                    >
                      <option value="">{t("asPipeline")}</option>
                      {(["hybrid", "dense", "sparse"] as const).map((x) => (
                        <option key={x} value={x}>
                          {t(`search.${x}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : null}
              {node.data.type === "reranker" ? (
                <>
                  <label className={field}>
                    {t("cfg.top_n")}
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={str("top_n")}
                      placeholder={t("asPipeline")}
                      disabled={!editable}
                      onChange={(e) => patchConfig("top_n", Number(e.target.value) || undefined)}
                      className={control}
                    />
                  </label>
                  <label className={field}>
                    {t("cfg.min_score")}
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={str("min_score")}
                      placeholder={t("asPipeline")}
                      disabled={!editable}
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
                  <label className={field}>
                    {t("cfg.model")}
                    <select
                      value={node.data.provider_instance_id ?? ""}
                      disabled={!editable}
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
                  <label className={field}>
                    {t("cfg.system_prompt")}
                    <textarea
                      rows={4}
                      value={str("system_prompt")}
                      disabled={!editable}
                      onChange={(e) => patchConfig("system_prompt", e.target.value || undefined)}
                      className="rounded-md border border-line-strong bg-surface p-2 text-sm font-normal"
                    />
                  </label>
                </>
              ) : null}
              {node.data.type === "mcp_tool" ? (
                <>
                  <label className={field}>
                    {t("cfg.tool")}
                    <select
                      value={str("tool_id")}
                      disabled={!editable}
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
                    <label className={field}>
                      {t("cfg.arguments")}
                      <textarea
                        rows={3}
                        defaultValue={JSON.stringify(cfg.arguments ?? {}, null, 1)}
                        disabled={!editable}
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
                      {tools.length === 0 ? (
                        <span className="text-xs text-fg-muted">{t("noTools")}</span>
                      ) : null}
                      {tools.map((x) => {
                        const ids = (cfg.tool_ids as string[] | undefined) ?? [];
                        return (
                          <label key={x.id} className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={ids.includes(x.id)}
                              disabled={!editable}
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
                  <label className={field}>
                    {t("cfg.test")}
                    <select
                      value={str("test")}
                      disabled={!editable}
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
                    <label className={field}>
                      {t("cfg.value")}
                      <input
                        value={str("value")}
                        disabled={!editable}
                        onChange={(e) => patchConfig("value", e.target.value)}
                        className={control}
                      />
                    </label>
                  ) : null}
                </>
              ) : null}
              {node.data.type === "guardrail" ? (
                <label className={field}>
                  {t("cfg.check")}
                  <select
                    value={str("check") || "grounded"}
                    disabled={!editable}
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
              {(() => {
                const into = edges.filter((e) => e.target === node.id).map((e) => nameOf(e.source));
                const out = edges.filter((e) => e.source === node.id).map((e) => nameOf(e.target));
                return (
                  <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <dt className="text-fg-muted">{t("comesFrom")}</dt>
                    <dd className="m-0">{into.join(", ") || "—"}</dd>
                    <dt className="text-fg-muted">{t("goesTo")}</dt>
                    <dd className="m-0">{out.join(", ") || "—"}</dd>
                  </dl>
                );
              })()}
              {editable && node.data.type !== "input" ? (
                <Button
                  size="sm"
                  variant="danger-outline"
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
            <div className="flex flex-col gap-2">
              <span className="text-sm font-semibold">
                {t("connection", { from: nameOf(edge.source), to: nameOf(edge.target) })}
              </span>
              <label className={field}>
                {t("branch")}
                <select
                  value={edge.data?.label ?? ""}
                  disabled={!editable}
                  onChange={(e) =>
                    setEdges((l) =>
                      l.map((x) =>
                        x.id === edge.id ? edgeOf(x.id, x.source, x.target, e.target.value) : x,
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
              {editable ? (
                <Button
                  size="sm"
                  variant="danger-outline"
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

          {editable ? (
            <details className="border-t border-divider pt-3">
              <summary className="cursor-pointer text-[13px] font-medium">
                {t("connectTitle")}
              </summary>
              <form
                aria-label={t("connectTitle")}
                onSubmit={(e) => {
                  e.preventDefault();
                  connect({ source: link.from, target: link.to }, link.label);
                }}
                className="mt-2 flex flex-col gap-2"
              >
                <p className="m-0 text-xs text-fg-muted">{t("connectHint")}</p>
                {(["from", "to"] as const).map((k) => (
                  <label key={k} className={field}>
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
                <label className={field}>
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
            </details>
          ) : null}
          {!custom && canEdit ? (
            <p className="m-0 flex items-start gap-2 rounded-md bg-sunken px-3 py-2 text-xs text-fg-secondary">
              <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
              {t("switchToEdit")}
            </p>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
