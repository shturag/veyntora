# 0035 · Knowledge tools, and agents that look things up

Status: accepted · 2026-11-07

## Context

MCP tools were only offered to the agent, which chooses on its own whether to call one. A tool that is really a knowledge source, such as a search of a city's website, was then skipped whenever the model thought it knew the answer. For example, "Gewerbe anmelden?" was answered from memory with an invented citation `[1]`. In warn mode such answers were shown with a warning.

Three problems:

- **Search depends on the model.** Whether the knowledge source is searched depends on the model's judgement and the wording of the question. Small models skip tools more often.
- **One source per call.** A tool result was one source, so a model citing the pages inside it cited sources that did not exist.
- **Invented citations shown.** A citation of a source that was never given was treated like a weak one: blocked in block mode, shown in warn mode.

## Decision

**1. Knowledge tools are a retrieval source.**
- **Setting:** `retrieval.tool_ids` lists up to five MCP tools.
- **Which tools qualify:** read-only tools that need no approval and are enabled on an active server.
- **Who may use them:** the same rules as for the agent apply. The asker must be in the tool's caller groups, and an external server must be allowed by the chatbot's data rule.
- **How they run:** every Fast answer searches them with the question, next to the documents. This also works with document retrieval off.
- **What they receive:** the question goes to the tool's only required text input, or to `query`. External servers get it masked when the data rule masks personal data, as for web search.
- **The agent:** in Agent mode the same tools are offered to the agent.
- **Logging:** every call is logged like an agent's call.

**2. Each block of a tool result is a source.**
- **Pages:** an embedded text resource (`resource`) or a `resource_link` keeps its address. Its title comes from `_meta.title`, from the resource, or from the address.
- **Text blocks:** a plain text block is a source without an address.
- **Numbering:** sources are numbered `[1]`, `[2]`, … across the answer.
- **Citations:** tool sources are cited like web pages and appear in the sources panel with "Open page". Their chunk ids start with `tool:`.
- **Who sees them:** they are the asker's own results. Shared chats and shared saved answers hide answers that cite them, as for web pages, because the viewer may not be allowed to use the tool.

**3. Invented citations are never shown.** An answer that cites a number no source has is blocked in every mode. The fact-check verdict does this before the threshold is considered.

**4. In chat, an agent looks things up before it answers.**
- **Setting:** `agent.lookup_first`, on by default.
- **Sent back once:** an answer written before any search or tool call goes back to the model once, with "look it up first".
- **No answer:** if the model answers from memory again, the result is "No answer found" with the reason in the trace. Sources the question brings, such as attached files and web results, count as looked up.
- **Automations are not affected.** Their agents may act on the event they are given.

The rule is enforced by Veyntora and not by the provider's `tool_choice`. This keeps it the same for every provider: some OpenAI-compatible servers reject `tool_choice: required`, and Anthropic does not allow forcing a tool while thinking is on.

## Consequences

- **The Essen-style chatbot needs no prompt.** It lists its search tool under Retrieval → Knowledge tools, and every question searches it.
- **Tool authors** should return one embedded resource per page, with its address and `_meta.title`. They should write descriptions that say when to use the tool, and set read-only hints. `docs/runbooks/local-dev.md` has the checklist.
- **Delays:** a slow knowledge tool delays every Fast answer by its response time. A failing tool doesn't stop the answer. The answer gets a warning and is written from the other sources, or becomes "no answer".
- **Rate limits:** a tool's per-user rate limit applies, and a limited tool is skipped.
- **Agent cost:** an agent that would have answered from memory now makes one more model call before giving "No answer found".
- **Earlier settings stay valid.** `tool_ids` defaults to empty and `lookup_first` to on.
