# Evaluation set: questions with known answers

A small, fictional company corpus (Nordwind Handels GmbH) and 20 questions for the Phase 1 acceptance checks:

- **Citations:** answerable questions must be answered with a citation into the expected document. The answer must contain the expected facts.
- **Grounded or silent:** questions the corpus does not answer must get the no-answer reply, never a guess.
- **Permissions:** `corpus/hr-salary-bands.md` is readable only by the HR group. Asked by an employee outside HR, its questions must find zero chunks and get the no-answer reply.
- **Latency:** p95 over the answerable questions.

These files are test fixtures. They are never loaded into a customer installation; the runner creates its own source and chatbot and removes them afterwards. The runner needs the provider keys (embeddings, reranker, LLM) to be configured, so it has not been run yet.
