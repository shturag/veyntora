from veyntora_graphs.phase_gate import gated_graph

# Phase 3: plan, call MCP tools, observe; interrupt before every write tool for approval.
graph = gated_graph("agent", phase=3)
