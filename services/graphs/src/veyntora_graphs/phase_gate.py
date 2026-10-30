"""Graphs that are registered with the server but not built yet.

Each one fails every run with a clear, typed error naming the phase that builds it, so no
caller can mistake a placeholder for an answer.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


class PhaseNotAvailableError(RuntimeError):
    def __init__(self, graph: str, phase: int) -> None:
        super().__init__(f"The {graph} graph is built in Phase {phase} and is not available yet.")
        self.graph = graph
        self.phase = phase


class GateState(TypedDict):
    messages: list[Any]


def gated_graph(name: str, phase: int) -> CompiledStateGraph[GateState, None, GateState, GateState]:
    def refuse(state: GateState) -> dict[str, Any]:
        del state
        raise PhaseNotAvailableError(name, phase)

    builder: StateGraph[GateState, None, GateState, GateState] = StateGraph(GateState)
    builder.add_node("not_available", refuse)
    builder.add_edge(START, "not_available")
    builder.add_edge("not_available", END)
    return builder.compile(name=name)
