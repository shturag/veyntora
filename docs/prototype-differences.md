# Deliberate differences from the prototype

The prototype (`design/prototype`, rag-platform-ui-v11) is the reference for screens, wording, layout and behaviour. Differences made on purpose:

## Everywhere

- **Name:** "Knowledge Assistant" → **Veyntora**, mark "K" → "V" (ADR 0002).
- **No sample data.** Lists, counts, KPIs and charts show real data or an empty state.
- **Dark mode** (not in the prototype). Dark tokens keep WCAG 2.2 AA contrast (`packages/ui/src/tokens.css`).
- **German UI** alongside English, switchable on the sign-in page and in the account menu.
- **Account menu** in the sidebar footer (language, theme, admin console link for admins, sign out). The prototype's footer shows a name and team only.

## Phase 0 placeholders

Screens built in later phases show their real title and summary plus a "This screen arrives in Phase N" card. The routes, navigation and permission checks are live.

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
