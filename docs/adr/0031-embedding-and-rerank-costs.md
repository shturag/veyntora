# 0031 · Embedding and reranker usage and prices

Status: accepted · 2026-11-03

## Decision

- **Input price:** embedding and reranker providers get an **input price** (EUR per million tokens), stored like an LLM's (`options.price_in_per_mtok_eur`). They have no output to price.
- **Token count:** adapters report the tokens of their last call (`last_tokens`). It is the service's own count where it reports one: OpenAI-style `usage`, or `meta.tokens` / `meta.billed_units` on rerank APIs. Otherwise it is an estimate of about four characters a token; TEI never reports, so it is always estimated.
- **Questions:** the search's query embedding and the reranking are recorded with the answer, like model calls. They are booked to the chatbot, person, cost centre and app key, so budgets and reports include them.
- **Indexing:** the embedding for each document (and semantic chunking) is recorded with cost centre `indexing` and no chatbot, because one index can serve several chatbots. Usage & budgets lists it as **Indexing documents**.
- **Provider page:** shows calls, tokens and cost for these providers too.

## Limits

- **Cohere search units:** prices are per token, while Cohere-style rerankers that bill per search unit report units, not tokens. Those rerankers are then estimated by text length.
- **History:** usage before this change was not counted.
