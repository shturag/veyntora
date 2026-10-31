# 0019 · MCP tools, the agent, approvals and Auto mode (Phase 3)

Status: accepted · 2026-10-31 · Phase 3

## Product owner decisions

- **MCP client:** the official `mcp` Python SDK (2.3.0), with Veyntora's own LangGraph loop around it. Not `langchain-mcp-adapters`.
- **Approvers:** a write tool whose policy names no approver group is approved by platform admins.
  - **Added on the strict side (not asked):** the person who asked never approves their own request, platform admin or not. Tell me if self-approval should be allowed.
- **Chat UI:** Veyntora's own components on `useStream`. Not assistant-ui.

## MCP servers and tools

- **Auth:** none, an API key, or OAuth client credentials.
  - Keys are in OpenBao at `mcp/{id}` and are read only by runtime services.
  - "Pass the user's token through" needs Keycloak token exchange and is planned for Phase 4. It is shown disabled.
- **Discovery** runs in a worker.
  - New tools arrive disabled.
  - Their class starts from the server's hints and fails safe: without a read-only hint, a tool is write.
  - A changed description or schema disables the tool for review again. A tool the server no longer offers is disabled.
  - A description that reads like instructions to the model is flagged, and enabling it needs an acknowledgement.
- **Before tools can be enabled,** a security reviewer signs the server off.
  - Destructive tools are never offered.
  - Write tools always need approval, whatever the policy says.
- **Policies per tool:** approver group, caller groups, and a rate limit per user per minute.
  - Every call is logged in `tool_calls` with a scrubbed argument summary.
- **External MCP servers** need the chatbot's data rule (`allowed_external_mcp_server_ids`). They are checked on publish and on every run, as for external models.

## The agent (`veyntora_api.agent`, graph `assistant`)

- **Nodes:** route → fast | agent_start → think → act → approve → … → finish, with the state kept in the LangGraph checkpoint.
  - A wait for approval resumes without repeating model calls.
  - Every node loads the asker's context again, so revoked access, a disabled tool or a disabled server takes effect at the next step.
- **Tools offered:**
  - the built-in `search_documents`, the chatbot's own retrieval with the asker's permissions;
  - bound MCP tools that are enabled, not destructive, on an active server, allowed for the asker's groups, and allowed by the data rule if external.
- **Tool results are numbered data.** The model is told not to follow instructions in them.
  - When the model is external and masking applies, results are masked before the model sees them, and tool arguments are unmasked before a tool runs.
- **Limits:** steps, active time (approval waits don't count) and the token budget.
- **The final answer is checked like a Fast answer:** citations, groundedness against all evidence, and the output guard. Only document passages become stored citations.
- **What is recorded:** the run (`runs`, with steps), the message (`run_id`, mode used, route reason), and usage per model turn.

## Approvals

- **Every write waits:** this is a LangGraph interrupt plus a row in `approvals`. Approvals expire after 24 hours, and every decision is audited.
- **Who resumes:** the asker's own chat resumes the run once the request is decided. The chat card checks the request every few seconds.
  - The resume carries only the approval id. The graph reads the decision from PostgreSQL, so sending a resume cannot approve anything.
  - Threads stay owned by their user, and no service identity can resume other people's runs.
  - **Limit:** if the asker closes the chat, the run continues when they next open it. Automations (Phase 4) will run under a service identity.
- **Stop** ends the run, and the request expires.

## Auto mode

1. A mode the user chose is used when the pipeline allows it. Auto only uses the agent when Agent mode is allowed.
2. **Rules,** each switchable on the Router page:
   - an action, only if the agent has write tools;
   - live data, only if it has MCP tools;
   - several sources.
3. **The router model,** if one is set.
4. **Otherwise Fast.** If Fast finds no answer, or one below the escalation threshold, the agent takes over. In that case Fast's tokens are not streamed.

## Not in this phase

- The Playground tests Fast only.
- Follow-up suggestions are shown for Phase 5.
- Testing a tool from its server page is not built.
- Delegated (user-token) MCP auth is planned for Phase 4.
