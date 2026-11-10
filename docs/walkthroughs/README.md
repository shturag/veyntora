# Walkthroughs

Short screen recordings of Veyntora, made from a running install. They fill in forms to show them but never save, create or publish anything.

## Build chatbots

| GIF | Shows |
|---|---|
| [01 · A simple chatbot](01-simple-chatbot.gif) | A general chatbot without documents: basics, retrieval off, the model and its instructions, chat features, details |
| [02 · A chatbot that answers from documents](02-rag-chatbot.gif) | Knowledge, ingestion, retrieval, reranking, generation with citations, guardrails, the Playground |
| [03 · A chatbot with tools](03-tools-chatbot.gif) | Agent mode, the router, knowledge tools, web search and the code sandbox, the pipeline as a flow |
| [04 · Automations](04-automations.gif) | Automations from a template or from scratch; trigger, steps, safety limits and runs |

## Connect

| GIF | Shows |
|---|---|
| [05 · Data sources](05-data-sources.gif) | Connecting SharePoint and a website; how documents are read and which files; a source's documents |
| [06 · Providers & keys](06-providers.gif) | Every kind of provider: language models, embeddings, rerankers, vector store, parsers, vision, guardrails, web search, code |
| [07 · Tools (MCP)](07-tools-mcp.gif) | MCP servers, their tools and approvals; adding a server |
| [08 · Channels & API](08-channels-api.gif) | The website widget, Microsoft Teams, Slack, email and app keys for the API |

## Operate

| GIF | Shows |
|---|---|
| [09 · Conversations](09-conversations.gif) | Answers to review, filtered by chatbot and outcome, with their sources |
| [10 · Knowledge health](10-knowledge-health.gif) | Gaps, contradictions, stale, unreadable and duplicate documents, each with its fix |
| [11 · Evaluation](11-evaluation.gif) | Scores by version, the publish gate, eval sets and their questions |
| [12 · Monitoring](12-monitoring.gif) | Requests by mode over time, alerts, provider health, Grafana dashboards |
| [13 · Integrations](13-integrations.gif) | Langfuse, Grafana and the virus scanner |
| [14 · Infrastructure](14-infrastructure.gif) | The services Veyntora runs on, their health, and versions of the settings |
| [15 · Usage & budgets](15-usage-budgets.gif) | Spend per chatbot, provider, group and cost centre; budgets and limits per user |

## Govern

| GIF | Shows |
|---|---|
| [16 · Users & groups](16-users-groups.gif) | People, roles, access reviews and a new group |
| [17 · Governance](17-governance.gif) | Retention, personal data, data subject requests, data rules, legal holds, platform roles |
| [18 · Audit log](18-audit-log.gif) | Every change, filtered by category, with before and after |

## For everyone

| GIF | Shows |
|---|---|
| [The chat](chat.gif) | Ask, read the answer with its sources, chats and knowledge, notifications, settings |
| [The admin console](admin-console.gif) | The overview and the sidebar's groups |

## Recording them again

With the stack running:

```bash
make walkthroughs
```

This signs in the e2e users, drives the UI with Playwright (`apps/web/scripts/record-walkthroughs.mjs`) and turns the frames into GIFs with Pillow (`scripts/walkthrough-gifs.py`). Steps for something an install does not have are skipped. The recordings show what is on the install, so record them on one without real people's data.
