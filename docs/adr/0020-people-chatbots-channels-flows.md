# 0020 · Users & groups, chatbot management, channels and custom flows (Phase 4)

Status: accepted · 2026-10-31 · Phase 4

## Product owner decisions

- **Suspend:** a person is blocked in Veyntora only; their Keycloak account is untouched. Every request and every agent step checks the flag, so suspension takes effect at once.
- **Approval delegates:** a person may name one delegate until an end date.
  - The delegate may decide what the approver could decide, never their own requests.
  - Both the approver of record (`approver_id`) and the person who clicked (`delegate_id`) are stored and audited.
- **App keys:** each key has its own service identity.
  - It is a user row with `is_service`, no Keycloak account, and is badged in Users & groups.
  - Admins give it groups and roles like a person; it never borrows a person's access.
  - Only the key's SHA-256 hash is stored; the key is shown once.
- **Teams and Slack:** both are built now: Microsoft 365 Agents SDK 1.8.0 for Teams, the official slack-sdk for Slack.
  - People are linked only through a Veyntora sign-in, never by e-mail.
- **Website widget:** sign-in happens in a pop-up, with no third-party cookies.
- **Graph editor:** the full custom editor, with React Flow 12.12.0 on the canvas.

## Users & groups

- **Keycloak groups** stay read-only; the sync owns them.
- **Veyntora groups** are either manual or rule-based.
  - Manual memberships can end on a date.
  - Rule groups match Keycloak attributes with `equals`, `not_equals`, `in`, `at_least`, `at_most` or `exists`, matching all or any conditions. Suspended people are left out.
  - Both kinds are refreshed hourly and after each Keycloak sync, and membership changes are written to OpenFGA.
- **Roles per chatbot** for a group go through the chatbot access rules, so the "at least one owner" rule still holds.
- **Effective access** is the union of a person's own grants and their groups' grants on every chatbot.

## Chatbot management

- **Pages:** cards, overview, duplicate (the copy starts as a draft owned by the copier), pause and resume, Knowledge, Access, and a 5-step wizard. Later wizard steps open only once the chatbot exists.
- **Knowledge weights and folders now take effect.**
  - Folders are path prefixes, checked in the PostgreSQL re-check, so they apply even before the index catches up.
  - A weight multiplies a source's passage scores after reranking and before the minimum-score check.
- **Access preview:** it is read-only and computed from grants; nobody is impersonated.

## Runs without a Keycloak token

- **Who needs them:** app keys, the widget and the Teams/Slack bots have no user token to forward to the graph server.
- **What the API signs:** an HS256 token with `VEY_INTERNAL_TOKEN_SECRET` (at least 32 characters), audience `veyntora-graphs`, valid 5 minutes, naming the identity.
- **How the graph server checks it:** it picks the check by the token's algorithm, and each path accepts only its own algorithm and key. That prevents algorithm-confusion attacks. Every permission is then checked as for any run.
- **Widget tokens** are separate: `vey_wt_…`, audience `veyntora-widget`, 15 minutes, one chatbot. Neither token kind can stand in for the other.

## Public API and widget

- **Public API:** `POST /v1/api/chatbots/{id|slug}/answers` and `.../conversations/{id}/resume`. They accept an app key or a person's Keycloak token, with a per-key rate limit.
- **Widget, step by step:**
  - `widget.js` adds an iframe of `/widget/<chatbot>`.
  - The web app sets `frame-ancestors` from the allowed websites, which are plain https origins (http only on localhost).
  - Sign-in happens in a first-party pop-up. It posts the widget token to the iframe, restricted to Veyntora's own origin and to the window that opened it.
  - The iframe keeps the token in memory only.
  - `Cross-Origin-Opener-Policy` is relaxed on `/widget/*` only, so the pop-up can reach its opener.

## Teams and Slack (`services/channels`, a runtime service)

- **Credentials:** they are in OpenBao at `channels/<id>`; the API writes them and the channels service reads them.
- **Teams:** the token's audience picks the chatbot's bot registration. The SDK's `JwtTokenValidator` must accept the token; any exception fails closed. Replies use the bot's MSAL credentials.
- **Slack:** the request is checked against the app's signing secret before anything is read. It is acknowledged at once, answered in the background, and Slack's retries are skipped. Sign-in links go only to the person who asked (an ephemeral message).
- **Linking:**
  - An unlinked account gets a one-time `/link/<code>` (10 minutes, stored hashed).
  - Opening it needs a session sign-in, never a key or widget token.
  - Links are listed and removable in Settings.
- **Conversations:** one Veyntora thread per platform conversation and person.
- **Approvals:** the reply links the Approvals page, and "continue" resumes only once the request is decided.
- **Not yet built:** approval cards inside Teams, and proactive messages when a decision arrives.

## Custom flows (`PipelineSpec.flow.custom`)

- **What runs:** when the switch is on, the chatbot runs its own flow. When it is off, the picture shows the standard pipeline, which runs.
- **How it runs:** the `assistant` graph runs the flow with two nodes, `flow_step` (walks the flow from the checkpoint) and `flow_approve` (interrupt). Each step type is one of Veyntora's own building blocks.
- **Rules checked before publishing:**
  - one input; no step that leads nowhere; everything reachable;
  - no loops, except an agent step and its toolbox;
  - complete conditions;
  - every way from an answer-writing step to an output passes a grounding check;
  - a writing tool called directly comes right after a human-approval step;
  - tools must be enabled and allowed by the data rule.
- **At run time:** a direct tool call still refuses to run without its granted approval.

## Limits

- **Not tested live yet:** Teams, Slack and widget sign-ins need a real tenant, workspace and intranet page.
- **Not built:** approval cards in Teams and Slack, proactive messages after a decision, and usage records linked to app keys.
- **Phase 7:** access reviews and GDPR export.
