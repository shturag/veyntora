from veyntora_spec.pipeline import FlowEdge, FlowNode, FlowNodeType, FlowSpec, flow_problems


def _flow(
    nodes: list[tuple[str, FlowNodeType, dict[str, object]]], edges: list[tuple[str, str, str]]
) -> FlowSpec:
    return FlowSpec(
        custom=True,
        nodes=[FlowNode(id=i, type=t, label=i, config=c) for i, t, c in nodes],
        edges=[FlowEdge(source=s, target=t, label=label) for s, t, label in edges],
    )


IN, OUT = ("in", FlowNodeType.INPUT, {}), ("out", FlowNodeType.OUTPUT, {})
RET = ("ret", FlowNodeType.RETRIEVER, {})
LLM = ("llm", FlowNodeType.LLM, {})
GROUND = ("ground", FlowNodeType.GUARDRAIL, {"check": "grounded"})


def test_the_standard_flow_is_valid_as_a_custom_flow() -> None:
    assert flow_problems(FlowSpec(custom=True)) == []
    assert flow_problems(FlowSpec(custom=False, edges=[])) == [], "not custom: not checked"


def test_every_answer_is_checked_for_grounding_before_it_is_shown() -> None:
    ok = _flow(
        [IN, RET, LLM, GROUND, OUT],
        [("in", "ret", ""), ("ret", "llm", ""), ("llm", "ground", ""), ("ground", "out", "")],
    )
    assert flow_problems(ok) == []
    skipped = _flow(
        [IN, RET, LLM, OUT], [("in", "ret", ""), ("ret", "llm", ""), ("llm", "out", "")]
    )
    assert any("grounding check" in p for p in flow_problems(skipped))
    cond = ("c", FlowNodeType.CONDITION, {"test": "no_sources"})
    side_door = _flow(
        [IN, RET, LLM, cond, GROUND, OUT],
        [
            ("in", "ret", ""),
            ("ret", "llm", ""),
            ("llm", "c", ""),
            ("c", "ground", "no"),
            ("c", "out", "yes"),
            ("ground", "out", ""),
        ],
    )
    assert any("grounding check" in p for p in flow_problems(side_door)), "every way, not one"


def test_loops_unreachable_steps_and_incomplete_steps_are_refused() -> None:
    loop = _flow(
        [IN, RET, LLM, GROUND, OUT],
        [
            ("in", "ret", ""),
            ("ret", "llm", ""),
            ("llm", "ret", ""),
            ("llm", "ground", ""),
            ("ground", "out", ""),
        ],
    )
    assert any("loop" in p for p in flow_problems(loop))
    lonely = _flow(
        [IN, RET, GROUND, OUT, ("x", FlowNodeType.RERANKER, {})],
        [("in", "ret", ""), ("ret", "ground", ""), ("ground", "out", ""), ("x", "out", "")],
    )
    assert any("not reachable" in p for p in flow_problems(lonely))
    half = _flow(
        [IN, ("c", FlowNodeType.CONDITION, {"test": "no_sources"}), OUT],
        [("in", "c", ""), ("c", "out", "yes")],
    )
    assert any("yes and a no" in p for p in flow_problems(half))
    tool = _flow([IN, ("t", FlowNodeType.MCP_TOOL, {}), OUT], [("in", "t", ""), ("t", "out", "")])
    assert any("choose the tool" in p for p in flow_problems(tool))
    two = _flow([IN, ("in2", FlowNodeType.INPUT, {}), OUT], [("in", "out", ""), ("in2", "out", "")])
    assert flow_problems(two) == ["a flow has exactly one input step"]


def test_an_agent_and_its_toolbox_may_loop() -> None:
    agent = ("agent", FlowNodeType.AGENT_LLM, {})
    box = ("tools", FlowNodeType.MCP_TOOL, {"tool_ids": []})
    ok = _flow(
        [IN, agent, box, GROUND, OUT],
        [
            ("in", "agent", ""),
            ("agent", "tools", ""),
            ("tools", "agent", ""),
            ("agent", "ground", ""),
            ("ground", "out", ""),
        ],
    )
    assert flow_problems(ok) == []
