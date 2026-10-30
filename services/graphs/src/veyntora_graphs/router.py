from veyntora_graphs.phase_gate import gated_graph

# Phase 3: intent and risk classification (small model + rules), Fast -> Agent escalation.
graph = gated_graph("router", phase=3)
