# Deliberate differences from the prototype

The prototype (`design/prototype`, rag-platform-ui-v11) is the reference for screens, wording, layout and behaviour. Differences made on purpose:

## Everywhere

- **Name:** "Knowledge Assistant" → **Veyntora**, mark "K" → "V" (ADR 0002).
- **No sample data.** Lists, counts, KPIs and charts show real data or an empty state.
- **Dark mode** (not in the prototype). Dark tokens keep WCAG 2.2 AA contrast (`packages/ui/src/tokens.css`).
- **German UI** alongside English, switchable on the sign-in page and in the account menu.
- **Account menu** in the sidebar footer (language, theme, admin console link for admins, sign out). The prototype's footer shows a name and team only.

## Routes that are states of another screen

`ChatFast.html`, `AgentRunning.html`, `ChatStates.html` and `Mobile.html` are states of the chat screen (`/chat/[id]`), not separate routes.

## Landing page (`index.html` → `/`)

| Prototype | Veyntora | Why |
|---|---|---|
| "router: auto · confidence 0.92" and "FAST RAG · ~1.2 s" in the flow | "How a request flows · example" and "FAST · cited answer" | The flow is an illustration; we do not claim measurements. |
| Stats strip "1.2 s · 94% · 12 tools · 0 keys" | Four product guarantees (Cited, Asks first, In-house, 0 keys shown) | The numbers were samples. Live figures belong in Monitoring (Phase 6). |
| Router card "Fast RAG 71% / Agent 29%" bar | Mode chips Fast · Auto · Agent | The split was sample data. |
| Evaluation card "0.94 faithfulness" chart | The real publish gate: faithfulness ≥ 0.85, answer relevance ≥ 0.80 | The gate values come from the brief. Scores are per version (Phase 6). |
| Sample bots "HR Policies · 1,240 users", "IT Helpdesk", "Legal Desk" | The wizard's templates (FAQ bot, Support agent with actions, Research assistant) + New chatbot | No demo chatbots. |
| Vault panel with sample secrets and "expires in 9 days" | The secrets guarantees (stored in OpenBao, last 4 + expiry shown, never read back, egress marked) | Sample data. |
| CTA "Try the full prototype" | "Ready to ask?" with Sign in / Admin console | Product, not prototype. |

## Sign-in (`SignIn.html`)

- The retention period ("Chats are kept for 90 days") comes from platform settings.
- Privacy notice and imprint links come from platform settings. Imprint is hidden until it is set.
- Error and "signed out" messages were added (expired login, suspended account, cancelled sign-in).

## Status (`Status.html`)

- Components and their state come from live health checks. The overall banner is computed, not written by hand.
- Notices ("Recent updates") come from the `status_notices` table. Without notices the page says so.
- "Microsoft Teams app" shows "Not set up" until a Teams channel exists (Phase 4).

## Admin console

- The rail lists only the areas the signed-in person may open (OpenFGA). A platform admin sees the full prototype list.
- **Pipelines** in the rail opens `/admin/pipelines` (choose a chatbot). The prototype jumps straight to one chatbot (`/admin/pipelines/[botId]`).
- **New chatbot, step 3:** “Save and fine-tune” opens every pipeline setting inside the wizard (`/admin/chatbots/new/pipeline/advanced`), with a way back to the questions and on to Access. The prototype links out of the wizard to the pipeline editor.
- **The wizard stays open.** The data rule for general chat and external providers is ticked in step 3 (by governance editors; others are told who must allow it). Checklist links lead to wizard pages; Playground, sources and providers open in a new tab, and the step refreshes when you come back.
- **New chatbot, step 4** shows everything the chatbot's Access page has: who may use it, experts for hand-off and the data rule. One “Save and continue” saves every panel with changes.

## Automations (Phase 5)

- **Automations:** the KPI "Failed runs" counts this week's failures. The list has no sample rows; an empty list says how to start.
- **New automation:** "Create draft" needs a chatbot (its model drafts the steps and its pipeline runs them). Templates leave out what they cannot know (tool, channel, data source) and list those as problems until they are chosen.
- **Builder:**
  - Steps can move up and down, and a "Before it can run" box lists what blocks activation.
  - Versions can be restored, and an event trigger shows its webhook token panel.
  - Autonomy options carry one-line explanations. *Act and report* still needs approvals for writing tools (principle 3).
- **Trigger:** the condition dialog became inline rule rows. "Fire once per" takes a field name of each item, instead of the prototype's "Contract (don't repeat)".
- **Agent step:** the step-type switch sits on the same page. "Test with sample event" starts a dry run (the result is on the run page) rather than showing inline output.
- **Approval step:** "Preview the approval in the inbox" became the editable-field and "Approver sees" choices. The real request appears in Approvals when a run waits.
- **Run trace:** "Replay in Playground" is not shown. An automation run is not one question, and its agent steps are listed with their tool calls instead. Messages the run sent are listed with their delivery state.

## Knowledge health (Phase 5)

- **Sections:** besides gaps and contradictions, the page lists stale, duplicate, reported and unreadable documents, because the scan finds them too.
- **Scan:** there are "Scan now" and "Settings" (which model checks contradictions, the nightly time, the stale and popular thresholds).
- **Suggested owner:** this is the source's owner (else the chatbot's owner), not a team name.

## Saved answers, hand-off, chat (Phase 5)

- **Saved answers:** shared answers that cite documents the viewer may not open are listed without their text. Share only offers the person's own groups plus "everyone who may use this assistant".
- **Ask a human expert:**
  - The "Send to" list comes from the chatbot's expert teams (Access page).
  - The same route lists "Questions for my team", "Expert answers to review" and "My questions", because the prototype has no screen for experts.
- **Chat options:**
  - "Share" opens "Share this chat".
  - The menu has Export chat and Delete. Save answer is a bookmark under each answer, and Ask a human expert stays under answers without a supported answer.
  - Rename is not built (the title comes from the first question).
- **Notifications:** a Notifications page and sidebar count were added; the prototype has no notification screen.

## Evaluation and versions (Phase 6)

- **Evaluation:** the gate settings sit on the page (owners edit them). Judge settings are a platform setting under "Settings". Runs use the starter's own permissions, so a run can show different results for different people.
- **Eval sets:** generated cases arrive marked "review" and do not count until a person saves them. Cases from thumbs-down answers start without a reference answer.
- **Versions:** "Start canary" is disabled while nothing is live. Overriding a failed gate needs a platform admin and a reason. The automatic rollback guard has its own settings on the page.

## Usage and budgets (Phase 6)

- **Spend split:** "Self-hosted (GPU)" shows the spend of self-hosted models from their prices; there are no GPU-hour numbers (Grafana has them).
- **Budgets:** besides chatbots, budgets can be set for groups and cost centres, by month, quarter or year. "When reached" also offers "switch Agent mode off". Every budget has a delete button.
- **Export:** CSV only, also grouped by provider or app key; Excel is not offered.
- **Limits per user:** exceptions are a multiple of the limits per group (2×, 3×, 5×, 10×).

## Conversations, Monitoring, Overview (Phase 6)

- **Conversations:**
  - Only rated answers are listed; the four filters are counts among them.
  - "Likely cause" lines come from recorded facts (no answer, guardrail, low groundedness, agent without tools, weak passages), not from a model.
  - "Edit router" and "Retry with OCR" are not on this page; their pages are linked instead.
- **Monitoring:**
  - "Error rate" became "Blocked answers" plus failed runs, because failed requests that never produced an answer are not recorded per request.
  - Providers show calls per instance, not p95 or GPU load (Grafana has those).
  - The Grafana link opens the configured address; there is no confirmation dialog.
- **Overview:**
  - "Needs attention" is built from real state.
  - GDPR deletion requests are not listed yet; they arrive with governance in Phase 7.
  - "Post status message to users" posts to the status page.

## Connect data source (Phase 6)

- **S3 and Website** have their own fields, readers chosen in Veyntora, and optional readers per folder.
- **File share (SMB)** stays disabled until its library is approved. Confluence and Database are labelled Phase 7.

## Governance, GDPR request, Audit log (Phase 7)

- **Governance:**
  - Retention adds an audit-log period (at least a year) and the access-review interval.
  - "Chatbots that may use external providers" lists every chatbot with its data rule (set per chatbot on its Access page).
  - The page adds **Platform roles** (Legal and Data protection officer are new) and a link to **Access reviews**.
- **Legal hold:** only the Legal role places or lifts a hold, by people's e-mail addresses and by chatbot.
- **GDPR request:**
  - The checks are real steps: mark identity verified, then approval by a DPO who is not the requester.
  - Personal memory is not listed, because Veyntora has none.
  - The confirmation report is signed JSON, not a PDF.
  - Traces are counted when the request is carried out.
- **Audit log:**
  - Categories add knowledge and governance.
  - "Revert to v7" is not on this page: versions are restored with a reason on the chatbot's Versions page, which "Open" links to.
  - Export also offers JSON lines with hashes. The chain status and the write-once archive are shown.
- **Access reviews** have their own page (`/admin/access-reviews`); the prototype has no screen for them.
- **Settings › Privacy:**
  - "Let the assistant remember my preferences" is removed, because there is no personal memory.
  - "Keep chat history" off deletes chats after a day.

## Connect data source (Phase 7)

- **Confluence, Database and File share (SMB)** are built, each with its own fields.
- Confluence and file shares map their own permissions (group map, SID map); databases use readers chosen in Veyntora, or a group column.
