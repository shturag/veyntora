"""Custom flows (graph editor, product owner 2026-10-31): run a chatbot's own flow.

The flow is data (PipelineSpec.flow, checked by flow_problems and the publish checks).
The assistant graph runs it with two nodes: `flow_step` walks the flow from the
checkpointed position, and `flow_approve` waits for a human approval (LangGraph
interrupt). Each step type is one of Veyntora's own building blocks, so the platform's
promises hold inside any flow:

- input: the question's personal data and safety checks (as in Fast);
- retriever / reranker: permission-aware search (top-k, search type, top-n, minimum score
  can be set per step);
- llm: an answer from the passages found so far (optional system prompt per step);
- agent_llm: the agent loop with the tools of the MCP step it loops with;
- mcp_tool (not in a loop): one call of one tool; a writing tool runs only after the
  human approval step before it was approved;
- condition: no_sources, grounded_below <value>, question_matches <words>;
- guardrail: grounded (citations and groundedness), input or output safety check;
- output: the answer is stored and shown.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any, Literal, TypedDict
from uuid import UUID

from veyntora_providers.interfaces import ChatMessage, Hosting, Usage
from veyntora_spec.pipeline import (
    AgentToolBinding,
    FlowEdge,
    FlowNode,
    FlowNodeType,
    PipelineSpec,
    SearchType,
)

from veyntora_api.agent import router as auto
from veyntora_api.agent import runner
from veyntora_api.agent import tools as agent_tools
from veyntora_api.agent.tools import BoundTool
from veyntora_api.rag import grounding, pipeline
from veyntora_api.rag.guard import Masker, check_input, check_output
from veyntora_api.rag.pipeline import NO_ANSWER_TEXT, Answer, RunContext, Source
from veyntora_api.rag.tracing import Trace

MAX_TRANSITIONS = 100


class FlowState(TypedDict, total=False):
    run_id: str
    at: str
    question: str
    guarded: str
    language: str
    need_mask: bool
    mask: dict[str, str]
    sources: list[dict[str, Any]]
    answer: str
    groundedness: float | None
    blocked: str | None
    warning: str | None
    used_agent: bool
    external: bool
    approved_for: str | None
    agent: runner.AgentState
    steps: list[dict[str, Any]]
    tokens_in: int
    tokens_out: int
    calls: list[dict[str, Any]]


Next = Literal["output", "approve_tool", "approve_agent"]


def _nodes(spec: PipelineSpec) -> dict[str, FlowNode]:
    return {n.id: n for n in spec.flow.nodes}


def _edges(spec: PipelineSpec, node: str) -> list[FlowEdge]:
    toolboxes = _toolboxes(spec)
    return [e for e in spec.flow.edges if e.source == node and e.target not in toolboxes]


def _toolboxes(spec: PipelineSpec) -> set[str]:
    from veyntora_spec.pipeline import _agent_toolboxes  # noqa: PLC0415 - shared rule

    return _agent_toolboxes(spec.flow)


def _follow(spec: PipelineSpec, node: str, label: str = "") -> str | None:
    edges = _edges(spec, node)
    for e in edges:
        if e.label == label:
            return e.target
    return edges[0].target if edges and not label else None


def _step(fs: FlowState, node: FlowNode, status: str, *, ms: int = 0, detail: str = "") -> None:
    fs.setdefault("steps", []).append(
        {
            "kind": node.type.value,
            "name": node.label or node.id,
            "status": status,
            "ms": ms,
            "detail": detail,
        }
    )


def _sources(fs: FlowState) -> list[Source]:
    return [
        Source(
            chunk_id=str(s.get("chunk_id") or f"step-{s['n']}"),
            document_id=str(s.get("document_id") or ""),
            title=s["title"],
            section=s.get("section") or "",
            text=s["text"],
            page=s.get("page"),
            score=float(s.get("score") or 0.0),
        )
        for s in fs.get("sources", [])
    ]


def _keep_sources(fs: FlowState, found: list[Source]) -> None:
    fs["sources"] = [
        {
            "n": n,
            "kind": "document",
            "title": s.title,
            "section": s.section,
            "text": s.text,
            "document_id": s.document_id,
            "chunk_id": s.chunk_id,
            "page": s.page,
            "score": s.score,
        }
        for n, s in enumerate(found, 1)
    ]


def _with(ctx: RunContext, node: FlowNode) -> RunContext:
    """The context with this step's own settings on top of the pipeline's."""
    cfg = node.config or {}
    spec = ctx.spec.model_copy(deep=True)
    if node.type is FlowNodeType.RETRIEVER:
        if cfg.get("top_k"):
            spec.retrieval.top_k = int(cfg["top_k"])
        if cfg.get("search_type") in {t.value for t in SearchType}:
            spec.retrieval.search_type = SearchType(cfg["search_type"])
    if node.type is FlowNodeType.RERANKER:
        if cfg.get("top_n"):
            spec.rerank.top_n = int(cfg["top_n"])
        if cfg.get("min_score") is not None:
            spec.rerank.min_score = float(cfg["min_score"])
    if node.type is FlowNodeType.LLM:
        if cfg.get("system_prompt"):
            spec.generation.system_prompt = str(cfg["system_prompt"])
        if node.provider_instance_id:
            spec.generation.llm_instance_id = node.provider_instance_id
    return replace(ctx, spec=spec)


def _tools_ctx(ctx: RunContext, tool_ids: list[Any]) -> RunContext:
    spec = ctx.spec.model_copy(deep=True)
    spec.agent.tools = [AgentToolBinding(tool_id=UUID(str(t))) for t in tool_ids if t]
    return replace(ctx, spec=spec)


def toolbox_of(spec: PipelineSpec, agent_node: str) -> list[Any]:
    nodes = _nodes(spec)
    ids: list[Any] = []
    for e in spec.flow.edges:
        if e.source == agent_node and e.target in _toolboxes(spec):
            ids += list(nodes[e.target].config.get("tool_ids") or [])
    return ids


def direct_tool(spec: PipelineSpec, node_id: str) -> tuple[FlowNode, str] | None:
    node = _nodes(spec).get(node_id)
    if node is None or node.type is not FlowNodeType.MCP_TOOL or not node.config.get("tool_id"):
        return None
    return node, str(node.config["tool_id"])


def tool_arguments(node: FlowNode, question: str) -> dict[str, Any]:
    raw = node.config.get("arguments") or {}
    return {
        k: (str(v).replace("{question}", question) if isinstance(v, str) else v)
        for k, v in (raw.items() if isinstance(raw, dict) else [])
    }


async def bound_direct_tool(env: runner.Env, node: FlowNode) -> BoundTool | None:
    ctx = _tools_ctx(env.ctx, [node.config.get("tool_id")])
    offered = await agent_tools.offered_tools(env.db, ctx, env.group_ids)
    return offered[0] if offered else None


def _usage(fs: FlowState, run_: pipeline._Run) -> None:
    fs["tokens_in"] = fs.get("tokens_in", 0) + run_.usage.prompt_tokens
    fs["tokens_out"] = fs.get("tokens_out", 0) + run_.usage.completion_tokens
    fs.setdefault("calls", []).extend(
        {"instance_id": str(i) if i else None, "in": u.prompt_tokens, "out": u.completion_tokens}
        for i, u in run_.calls
    )
    fs["external"] = fs.get("external", False) or run_.egress


def _masker(fs: FlowState) -> Masker:
    by_token = dict(fs.get("mask") or {})
    return Masker(by_value={v: k for k, v in by_token.items()}, by_token=by_token)


# ---------------------------------------------------------------- steps


async def _input(
    env: runner.Env, fs: FlowState, node: FlowNode, history: list[ChatMessage]
) -> str | None:
    run_ = pipeline._Run(started=time.perf_counter())
    guarded, masker, _pii, need_mask, stop = await pipeline._guard_input(
        env.adapters, env.ctx, run_, fs["question"], language=fs["language"], tr=Trace(None)
    )
    fs["guarded"], fs["need_mask"], fs["mask"] = guarded, need_mask, dict(masker.by_token)
    fs["warning"] = run_.warning
    _usage(fs, run_)
    if stop is not None:
        fs["blocked"] = stop.text
        fs["warning"] = stop.warning
        _step(fs, node, "blocked", detail=stop.warning or "")
        return _to_output(env.ctx.spec)
    _step(fs, node, "done")
    return _follow(env.ctx.spec, node.id)


async def _router(env: runner.Env, fs: FlowState, node: FlowNode, mode: str | None) -> str | None:
    offered = await agent_tools.offered_tools(env.db, env.ctx, env.group_ids)
    chosen = await auto.route(env.adapters, env.ctx, fs["question"], mode, offered)
    _step(fs, node, "done", detail=f"{chosen.mode}: {chosen.reason}")
    return _follow(env.ctx.spec, node.id, chosen.mode) or _follow(env.ctx.spec, node.id)


async def _retriever(env: runner.Env, fs: FlowState, node: FlowNode) -> str | None:
    t0 = time.perf_counter()
    ctx = _with(env.ctx, node)
    found = await pipeline.retrieve(env.db, env.adapters, ctx, fs.get("guarded") or fs["question"])
    _keep_sources(fs, found)
    if ctx.hosting(ctx.spec.retrieval.embedding_instance_id) is Hosting.EXTERNAL:
        fs["external"] = True
    _step(
        fs,
        node,
        "done",
        ms=round((time.perf_counter() - t0) * 1000),
        detail=f"{len(found)} passages",
    )
    return _follow(env.ctx.spec, node.id)


async def _reranker(env: runner.Env, fs: FlowState, node: FlowNode) -> str | None:
    t0 = time.perf_counter()
    ranked, _ = await pipeline.rerank(
        env.adapters, _with(env.ctx, node), fs["question"], _sources(fs)
    )
    _keep_sources(fs, ranked)
    _step(
        fs, node, "done", ms=round((time.perf_counter() - t0) * 1000), detail=f"{len(ranked)} kept"
    )
    return _follow(env.ctx.spec, node.id)


async def _llm(
    env: runner.Env, fs: FlowState, node: FlowNode, history: list[ChatMessage]
) -> str | None:
    t0 = time.perf_counter()
    ctx = _with(env.ctx, node)
    run_ = pipeline._Run(started=time.perf_counter())
    masker = _masker(fs) if fs.get("need_mask") else None
    pii = await pipeline._adapter(env.adapters, ctx.spec.guardrails.pii_instance_id)
    text = await pipeline._generate(
        env.adapters,
        ctx,
        run_,
        question=fs.get("guarded") or fs["question"],
        history=history,
        sources=_sources(fs),
        masker=masker,
        pii=pii,
        language=fs["language"],
        emit=None,
        tr=Trace(None),
    )
    if masker is not None:
        fs["mask"] = dict(masker.by_token)
    _usage(fs, run_)
    fs["answer"] = "" if grounding.is_no_answer(text) else text.strip()
    _step(fs, node, "done", ms=round((time.perf_counter() - t0) * 1000))
    return _follow(env.ctx.spec, node.id)


async def _agent(
    env: runner.Env, fs: FlowState, node: FlowNode, history: list[ChatMessage]
) -> tuple[str | None, Next | None]:
    ctx = _tools_ctx(env.ctx, toolbox_of(env.ctx.spec, node.id))
    agent_env = replace(env, ctx=ctx)
    st = fs.get("agent")
    if not st:
        st = runner.start(
            ctx,
            UUID(fs["run_id"]),
            fs["question"],
            guarded=fs.get("guarded") or fs["question"],
            history=history,
            language=fs["language"],
            masker=_masker(fs),
            need_mask=bool(fs.get("need_mask")),
        )
    while True:
        if st.get("pending"):
            st, waiting, _tool = await runner.act(agent_env, st)
            if waiting:
                fs["agent"] = st
                return node.id, "approve_agent"
        if st.get("final") is not None or st.get("stopped"):
            break
        st = await runner.think(agent_env, st)
    fs["used_agent"] = True
    fs["answer"] = runner._masker(st).unmask(st.get("final") or "").strip()
    fs["sources"] = list(st.get("sources", []))
    fs["external"] = fs.get("external", False) or bool(st.get("external"))
    fs["tokens_in"] = fs.get("tokens_in", 0) + st.get("tokens_in", 0)
    fs["tokens_out"] = fs.get("tokens_out", 0) + st.get("tokens_out", 0)
    fs.setdefault("calls", []).extend(st.get("calls", []))
    fs.setdefault("steps", []).extend(st.get("steps", []))
    fs["agent"] = {}
    _step(fs, node, "done")
    return _follow(env.ctx.spec, node.id), None


async def _tool(env: runner.Env, fs: FlowState, node: FlowNode) -> str | None:
    tool = await bound_direct_tool(env, node)
    if tool is None:
        fs["blocked"] = "A tool this flow needs is not available."
        _step(fs, node, "rejected", detail="tool not available")
        return _to_output(env.ctx.spec)
    if tool.requires_approval and fs.get("approved_for") != node.id:
        # flow_problems and the publish checks keep this from happening; refuse anyway.
        fs["blocked"] = "This action needs an approval first."
        _step(fs, node, "rejected", detail="not approved")
        return _to_output(env.ctx.spec)
    args = tool_arguments(node, fs["question"])
    outcome = await agent_tools.call_mcp(
        env.db,
        tool,
        args,
        user_id=env.ctx.user_id,
        run_id=UUID(fs["run_id"]),
        secrets=env.secrets,
        connect=env.connect,
    )
    fs["approved_for"] = None
    n = len(fs.get("sources", [])) + 1
    fs.setdefault("sources", []).append(
        {
            "n": n,
            "kind": "tool",
            "title": f"{tool.server_name}: {tool.tool_name}",
            "section": "",
            "text": outcome.text[:6000],
        }
    )
    if tool.external:
        fs["external"] = True
    _step(fs, node, "failed" if outcome.is_error else "done", detail=agent_tools.summary(args))
    return _follow(env.ctx.spec, node.id)


def _condition(env: runner.Env, fs: FlowState, node: FlowNode) -> str | None:
    cfg = node.config or {}
    test = cfg.get("test")
    if test == "no_sources":
        hit = not fs.get("sources")
    elif test == "grounded_below":
        check = grounding.check(fs.get("answer") or "", [s.text for s in _sources(fs)])
        fs["groundedness"] = check.score
        hit = check.score < float(cfg.get("value") or 0.0)
    else:
        words = [w for w in re.split(r"[\s,]+", str(cfg.get("value") or "").lower()) if w]
        hit = any(w in fs["question"].lower() for w in words)
    _step(fs, node, "yes" if hit else "no", detail=str(test))
    return _follow(env.ctx.spec, node.id, "yes" if hit else "no")


async def _guardrail(env: runner.Env, fs: FlowState, node: FlowNode) -> str | None:
    spec = env.ctx.spec
    check = (node.config or {}).get("check", "grounded")
    passed, why = True, None
    if check == "grounded":
        result, problem, g = pipeline.verdict(
            spec, fs.get("answer") or "", _sources(fs), blocking=True
        )
        fs["groundedness"] = g.score
        passed = bool(fs.get("answer")) and result != "blocked"
        why = problem or ("no answer" if not fs.get("answer") else None)
    elif check == "input":
        guard = await pipeline._adapter(env.adapters, spec.guardrails.input_guardrail_instance_id)
        out = await check_input(
            spec, fs.get("guarded") or fs["question"], pii_found=False, guard=guard
        )
        passed, why = out.action == "allow", out.reason
    else:
        guard = await pipeline._adapter(env.adapters, spec.guardrails.output_guardrail_instance_id)
        out = await check_output(spec, fs["question"], fs.get("answer") or "", guard=guard)
        passed, why = out.action == "allow", out.reason
    _step(fs, node, "pass" if passed else "fail", detail=why or "")
    if passed:
        return _follow(spec, node.id, "pass") or _follow(spec, node.id)
    target = _follow(spec, node.id, "fail")
    if target is None:
        fs["blocked"] = fs.get("blocked") or (why or "not supported by the sources")
        return _to_output(spec)
    return target


def _to_output(spec: PipelineSpec) -> str:
    return next(n.id for n in spec.flow.nodes if n.type is FlowNodeType.OUTPUT)


async def _run(
    env: runner.Env, fs: FlowState, node: FlowNode, history: list[ChatMessage], mode: str | None
) -> tuple[str | None, Next | None]:
    """One step: the next step's id, or a reason to stop here (an approval wait)."""
    kind = node.type
    if kind is FlowNodeType.AGENT_LLM:
        return await _agent(env, fs, node, history)
    if kind is FlowNodeType.HUMAN_APPROVAL:
        return node.id, "approve_tool"
    nxt: str | None
    if kind in {FlowNodeType.INPUT, FlowNodeType.LLM}:
        step = _input if kind is FlowNodeType.INPUT else _llm
        nxt = await step(env, fs, node, history)
    elif kind is FlowNodeType.ROUTER:
        nxt = await _router(env, fs, node, mode)
    elif kind is FlowNodeType.CONDITION:
        nxt = _condition(env, fs, node)
    else:
        steps = {
            FlowNodeType.RETRIEVER: _retriever,
            FlowNodeType.RERANKER: _reranker,
            FlowNodeType.MCP_TOOL: _tool,
            FlowNodeType.GUARDRAIL: _guardrail,
        }
        nxt = await steps[kind](env, fs, node)
    return nxt, None


async def advance(
    env: runner.Env, fs: FlowState, *, history: list[ChatMessage], mode: str | None
) -> tuple[FlowState, Next]:
    """Run steps from `fs["at"]` until the output or an approval wait."""
    spec = env.ctx.spec
    nodes = _nodes(spec)
    for _ in range(MAX_TRANSITIONS):
        node = nodes.get(fs.get("at") or "")
        if node is None:
            fs["blocked"] = "The flow has no next step."
            fs["at"] = _to_output(spec)
            return fs, "output"
        if node.type is FlowNodeType.OUTPUT:
            _step(fs, node, "done")
            return fs, "output"
        nxt, waiting = await _run(env, fs, node, history, mode)
        if waiting is not None:
            fs["at"] = node.id
            return fs, waiting
        fs["at"] = nxt or _to_output(spec)
    fs["blocked"] = "The flow did not finish."
    fs["at"] = _to_output(spec)
    return fs, "output"


def approval_target(spec: PipelineSpec, approval_node: str) -> str | None:
    """The step a human approval step guards: its onward branch, never the rejected one."""
    return next((e.target for e in _edges(spec, approval_node) if e.label != "rejected"), None)


def after_rejection(spec: PipelineSpec, approval_node: str) -> str | None:
    return _follow(spec, approval_node, "rejected")


def result(env: runner.Env, fs: FlowState) -> Answer:
    """The stored answer: blocked or no answer when a check failed or nothing was found."""
    spec = env.ctx.spec
    no_answer = NO_ANSWER_TEXT.get(fs.get("language", "en"), NO_ANSWER_TEXT["en"])
    sources = _sources(fs)
    calls = [
        (UUID(c["instance_id"]) if c.get("instance_id") else None, Usage(c["in"], c["out"]))
        for c in fs.get("calls", [])
    ]
    base = Answer(
        "no_answer",
        no_answer,
        sources=sources,
        groundedness=fs.get("groundedness"),
        warning=fs.get("blocked") or fs.get("warning"),
        external_egress=bool(fs.get("external")),
        usage=Usage(fs.get("tokens_in", 0), fs.get("tokens_out", 0)),
        calls=calls,
    )
    answer = _masker(fs).unmask(fs.get("answer") or "")
    if fs.get("blocked"):
        base.outcome = "blocked"
        base.text = spec.guardrails.blocked_message if fs.get("answer") else no_answer
        return base
    if not answer:
        return base
    check = grounding.check(answer, [s.text for s in sources])
    base.outcome, base.text = "answered", answer
    base.groundedness = check.score
    base.cited = [(n, sources[n - 1]) for n in check.cited if sources[n - 1].document_id]
    return base
