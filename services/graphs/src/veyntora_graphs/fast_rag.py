from veyntora_graphs.phase_gate import gated_graph

# Phase 1: query rewrite, hybrid search with ACL filter, RRF, rerank, cited generation,
# groundedness check.
graph = gated_graph("fast_rag", phase=1)
