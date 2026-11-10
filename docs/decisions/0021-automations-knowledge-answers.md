# 0021 · Automations, knowledge health, saved answers, hand-offs, delegated tools

Status: accepted · 2026-10-31

## Product owner decisions

- **Posting to Teams:** automations post with the chatbot's own Teams bot (proactive messages). The bot must be added to the team channel; the channel is remembered then.
- **Email:** through an SMTP relay set under Channels & API (password write-only in OpenBao). Mailpit 1.31.5 catches mail in the local stack.
- **Contradiction checks:** an admin chooses the model. An external one may read a pair of passages only when every chatbot using both documents' sources allows that provider, and the scan is marked external in the audit log.
- **Delegated MCP auth:** built now, with Keycloak standard token exchange.
- **Automations run as their own service identity**, with no access until an admin grants it (like app keys).
- **Expert answers can join the knowledge base** for groups the expert chooses, after a chatbot owner or knowledge admin reviews them.
- **Holidays:** schedules may skip public holidays (`holidays` 0.106, offline).
- **Approve / Reject in Teams and Slack** are built.
- **Connectors** (Confluence, file share, S3, websites, databases) move to operations (ADR 0022).
- **Follow-up suggestions** are built, off by default per chatbot.

## Automations

- **Spec** (`packages/spec`, `AutomationSpec`): one trigger (schedule, event, file, watcher), ordered steps (agent, condition, approval, tool, notify) and safety limits. Each save is a version; runs name the version they used, and older versions can be restored.
- **Autonomy:**
  - *Suggest only:* read tools only; tool steps and messages are only shown on the run.
  - *Act with approval:* every write and message needs an approval step before it (checked at activation).
  - *Act and report:* messages go out without asking and the owner gets a report.
  - Writing tools always need an approval, in every mode (principle 3).
- **Runs** execute on the graph server (`automation` graph) with an API-signed token naming the automation's service identity; a run is refused for any other identity.
  - Agent steps reuse the agent loop with the chatbot's live pipeline: input checks on the task, grounding checks on the result. Without a supported answer the run stops, unless the next step is a condition.
  - Approvals use the LangGraph interrupt; the workers resume the run once the approval is decided (read from PostgreSQL, as in chat).
- **Approvals** may need two people, time out after a set number of hours, and then cancel or escalate once to another group. The approver may correct one chosen field. Whoever started a manual run may not approve it.
- **Triggers:**
  - schedules use cron in their own time zone, skipping holidays;
  - event webhooks carry a `vey_wh_` token, stored as a hash only, with conditions, duplicate skipping and working hours;
  - file triggers fire on added or changed documents, before or after indexing;
  - watchers call a read tool and fire once per item.
- **Limits:** cost per run, runs per hour, retries (then the owner is told).
- **"Create draft" from a description:** the chatbot's model proposes a spec (graph `automation_draft`, with the admin's own token). Unknown tools are dropped, the result is validated, and it is only a draft.

## Notifications and delivery

- **Notifications** are in-app (sidebar count, Notifications page). They are also queued as deliveries to the person's Teams or Slack chat and email, each of which people can turn off in Settings.
- **Deliveries** are sent by the channels service (Teams and Slack, using the chatbot's bot) or the workers (email). They are retried 3 times, then kept as failed with the error. Runs show what they sent.
- **Teams and Slack** remember the channels the bot joins and linked people's personal chats. Approval cards (Adaptive Card, Block Kit) count only for the linked person who presses, with the inbox's rules.
- A Teams or Slack conversation waiting for an approval goes on by itself once it is decided, and the answer is posted there. Requesters are told about decisions.

## Knowledge health

- **Scan:** a nightly scan at a set local time, or "Scan now". It finds parse failures, stale-but-popular documents, duplicates (same file, or near-identical shingles), contradictions and gaps.
- **Contradictions:**
  - Candidates are similar passages of different documents. A maintenance-only vector-store interface (`MaintenanceStore`, Qdrant) has no ACL filter; it is never used for answers.
  - An LLM judges each pair. Owners are told at once, but passage text goes only to owners who may read both documents.
- **Gaps:** groups of unanswered questions (the new `messages.outcome` column), shown with masked examples only.
- **Actions:**
  - notify the owner;
  - ask owners to resolve by a date;
  - exclude a document from answers (reversible; checked in the retrieval re-check);
  - dismiss, optionally for good.
- **Report wrong source** in the Source viewer creates an issue and tells the document's owners.

## Saved answers, shared chats, hand-offs

- **Saved answers:**
  - A saved answer is a snapshot that keeps each cited document's content hash.
  - Shared answers are shown only to people who may open every cited document; others see that it exists, not its text.
  - A changed hash marks the answer stale.
  - Refreshing asks again as the saver (graph `answer_once`), so it never uses more than their access. The workers refresh shared answers that asked for it.
- **Shared chats** are read-only links (people, my team, or the assistant's users) with the same per-viewer check; sources are optional.
- **Hand-offs:**
  - Each chatbot has expert groups (Access page). The asker chooses urgency, includes the conversation if they want, and picks the reply channel.
  - The team answers in Veyntora, and the reply shows in the chat.
  - An expert answer joins an "Expert answers" upload source readable by exactly the chosen groups, after review.

## Delegated MCP auth

- **How it works:** a tool on a delegated server acts as the person.
  - The graph server or workers ask the API (`POST /internal/delegated-token`, a 60-second API-signed request).
  - The API exchanges the person's own access token from their most recent web sign-in (server-side session, refreshed when needed) at Keycloak for a token whose audience is the tool (RFC 8693, standard token exchange).
  - That token is used for one call and is never stored, logged or written to run records. Aegra persists the run's user object, so the token never goes there.
- **Limits:**
  - Service identities (automations, app keys) are never offered delegated tools.
  - Teams and Slack users get them only while signed in to Veyntora on the web; the tool says so otherwise.
  - Discovery runs as the server's owner.
- **Keycloak setup:** standard token exchange is enabled on the `veyntora` client (dev realm). Each tool's audience must be a Keycloak client made available to `veyntora` through an audience mapper; otherwise the exchange is refused and the tool says an admin must allow it. Verified against the local Keycloak 26.8.1 with a temporary client, which was removed afterwards.

## Follow-up suggestions

- **Setting:** `generation.suggest_follow_ups` per chatbot, off by default. People can turn the suggestions off.
- **How they are made:** one small call to the answer model (already allowed for the chatbot), with personal data masked exactly as for the answer. Only questions ending in "?" are kept, up to three. The extra call is counted in usage.

## Migrations

- **0012:** automations, versions, seen keys, runs, approvals, channel destinations, notifications, deliveries.
- **0013:** knowledge health.
- **0014:** saved answers, hand-offs, shared chats, chatbot experts.
- **Pinned:** `croniter` 6.2.4, already locked through aegra, is now pinned directly.

## Not tested live

- **Teams, Slack and the SMTP relay:** posting, buttons and conversation resume have not been tried against a real Teams tenant, Slack workspace or SMTP relay. Email was verified locally through Mailpit.
- **LLM-dependent parts** have not run with a real model: contradiction judging, automation drafts, agent steps and follow-ups.
