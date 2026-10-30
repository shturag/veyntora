import pytest
from veyntora_graphs.agent import graph as agent
from veyntora_graphs.phase_gate import PhaseNotAvailableError
from veyntora_graphs.router import graph as router


@pytest.mark.parametrize(("graph", "phase"), [(agent, 3), (router, 3)])
async def test_unbuilt_graphs_refuse_instead_of_answering(graph: object, phase: int) -> None:
    with pytest.raises(PhaseNotAvailableError, match=f"Phase {phase}"):
        await graph.ainvoke({"messages": [{"role": "user", "content": "hi"}]})  # type: ignore[attr-defined]
