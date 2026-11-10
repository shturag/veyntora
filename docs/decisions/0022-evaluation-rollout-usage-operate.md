# 0022 · Evaluation, canary roll-out, usage and budgets, operating screens, S3 and website connectors

Status: accepted · 2026-10-31

## Product owner decisions

- **Evaluation metrics:** the Ragas metric definitions (faithfulness, answer relevance, context recall and precision) are implemented in our own code, with the judge model called through our providers. No new dependency; data rules apply to the judge like to any model.
- **Conversations review** shows only answers people rated. Opening one is recorded in the audit log.
- **Canary:** steps are manual (10% → 50% → everyone), plus an automatic rollback guard.
- **Connectors now:** S3, websites and file shares (SMB). Confluence and databases move to governance (ADR 0023). SMB waits for approval of its library (see Open).

## Evaluation and the publish gate

- **Eval sets** hold cases (question, reference answer, sources it must cite, expected tools, "should say it doesn't know"). Cases come from:
  - typing them in;
  - CSV import;
  - generation from a source's passages (marked to review, never counted before a person reviews them);
  - thumbs-down answers.
- **Runs** execute every case as the person who started the run (their permissions), on the draft or the live version. The agent is used for cases with expected tools, and writes are refused. The judge's tokens are counted as usage.
- **The gate** (per chatbot, owners): which sets must pass, minimum faithfulness and relevance, and the largest drop allowed against live. A run counts only for the exact draft it ran on (spec hash); changing the draft needs a new run. Publishing and starting a canary check the gate. Only a platform admin may override it for a canary, with a reason, and the override is audited.

## Canary roll-out and rollback

- People get the canary by a stable share of a hash of chatbot and person, so the same person stays on the same version.
- **Promote** makes the canary live and archives the old live version, which stays one click away. **Stop** archives the canary and keeps its numbers. **Rollback** to any earlier published version needs a reason (audited) and stops a running canary.
- **The guard** (workers, every 5 minutes) compares canary and live over the time the canary has run. It rolls back by itself only with enough answers (default 30) and when a threshold is crossed: the blocked share, a rise in "no answer", or a rise in thumbs-down. The owner is told. The guard can be turned off per chatbot.

## Usage and budgets

- **Usage records** now carry the asker's cost centre (from their first group that has one) and the app key. The key's id travels in the API-signed token to the graphs, never the key itself.
- **Budgets** apply per chatbot, per group (what its current members spend) or per cost centre, by month, quarter or year. When a run starts, every budget that applies is checked; of those at their limit, the strictest action wins:
  - block (refused with the reason);
  - Fast only (Agent mode off);
  - the budget's smaller model (data rules apply to it as always);
  - warn only.
- **Alerts:** the budget's owner (by default, whoever set it) and the scope's owner are told once per period at the alert threshold and once at the limit.
- **Limits per user:** questions per hour (refused over it), Agent runs per day (Agent mode off over it), upload storage (an upload over it is refused). Groups can get a multiple of the limits. Service identities are limited by budgets only.
- **Finance export:** CSV by cost centre, chatbot, group, provider or app key. It is audited, and cells that spreadsheets would run as formulas are escaped.

## Operating screens

- **Conversations review:**
  - Filtered by what went wrong. Masked with the local personal-data rules (e-mail, IBAN, phone and card numbers), and the asker is shown by team only.
  - Passages of cited documents are shown only to reviewers who may read those documents.
  - Actions: mark reviewed, add to an eval set, ask the document owner, open the run trace (or Langfuse when its browser address is set), open in Playground.
- **Monitoring:** built from what Veyntora records (answers, ratings, runs, usage), with links to Langfuse and Grafana. These links show only when `VEY_LANGFUSE_BROWSER_URL` and `VEY_GRAFANA_BROWSER_URL` are set. The chart colours are two categorical tokens, `--vey-series-1` and `--vey-series-2`, checked for colour-vision deficiency in light and dark.
- **Overview:** today's numbers, a "needs attention" list built from real state, system status and chatbots today. It lists:
  - drafts held by the gate;
  - running canaries;
  - answers to review;
  - failed ingestion;
  - budgets past their alert;
  - keys expiring within 14 days;
  - degraded services.

  Status messages to users can be posted and ended; both are audited and shown on the status page.

## S3 and website sources

- Neither system has permissions Veyntora can map person by person. Readers are therefore chosen in Veyntora, with optional readers per folder (S3 prefix or website path; the longest match wins and replaces the source's readers below it). Changing them re-applies permissions to every document.
- **S3:** AWS or on-premises S3 stores (endpoint URL). It needs only list and read rights. The secret access key is write-only in OpenBao, like every secret.
- **Websites:** crawled breadth-first from the start pages. The crawler:
  - follows only the start pages' hosts and skips redirects elsewhere;
  - keeps to the chosen paths, depth and page limit;
  - respects robots.txt and nofollow.

  Pages are stored as UTF-8 HTML and parsed like uploads.
- **One listing sync for both:**
  - Changed files are downloaded, scanned by ClamAV and indexed like uploads.
  - Unchanged files (same ETag or content hash) are skipped.
  - Files no longer listed are removed only after a complete listing. A crawl cut short by its page limit or by errors removes nothing.
- **Tests:** the crawl and sync run against a mocked site. The S3 reader runs against SeaweedFS (the image compose uses) in a test container.

## Open

- **SMB file shares** need a new library, `smbprotocol` (pure Python, MIT). Per the dependency rule it waits for approval. Its source type, its place in Connect data source and the listing sync are ready for it.
- Monitoring has no per-provider latency or GPU numbers; those are in Grafana.
