# 0017 · Own models (BYOK) and user settings

Status: accepted · 2026-10-31

## Own models (product owner: own endpoint and model; fall back on failure)

- **What a user brings:** an LLM adapter (`openai_compatible` or `anthropic`), an endpoint, a model and a key. It is used for answer generation and question rewriting in their chats.
- **One model for chats:** at most one own model is marked "My chats". "Agent tasks" is reserved for the agent (ADR 0018–0019).
- **When it is used:** only on chatbots whose data rule has `allow_byok`. If that rule also requires masking, the pipeline must have a PII provider. Otherwise the own model is not used for that chatbot and the chatbot's own model answers.
- **Data rules still apply:** an own model always counts as external. Personal data is masked before it, as for any external model, and the answer is marked "external".
- **Fallback:** if the own key is rejected or the call fails before producing output, the chatbot's own model answers. The user is told: "Your own model did not answer; the assistant's model answered instead."
- **The Playground** tests the chatbot as configured. It never uses the tester's own model or preferences.
- **The key is write-only:** it is stored at `users/{user_id}/{key_id}` in OpenBao (ADR 0004). Only its last 4 characters and expiry are returned.
- **Testing a key:** before a key is stored, the API calls the endpoint's health check with it (`/models` for OpenAI-compatible). It holds the value at that moment anyway; the value is never logged or returned.
- **Replacing a key:** this uses the same grace period as provider keys (ADR 0016). Removing an own model deletes every version.
- **Usage:** each call is recorded with `byok = true` and `external = true`, no provider instance and cost 0, since it is billed to the user's own account.

## Endpoints typed by users must be public (`veyntora_providers.netguard`)

- **Why:** Veyntora calls these endpoints from inside the network. Allowing internal addresses would let a user reach OpenBao, PostgreSQL or the cloud metadata service through it.
- **What is allowed:** only `https://` URLs without credentials whose every resolved address is globally routable. Loopback, private, link-local, carrier-grade NAT, reserved and multicast addresses are refused, and so are IPv4-mapped IPv6 forms of them.
- **When it is checked:** when the endpoint is saved, when a key is tested, and again before each use.
- **Known limit:** a DNS answer can still change between the check and the connection (DNS rebinding). Redirects are not followed by our HTTP client. Pinning the checked address for the connection is a hardening item for the security review (governance (ADR 0023)).

## User settings

- **Stored on the server:** `users.preferences` holds the answer language, answer length and default assistant.
  - **Answer language** applies only when the chatbot answers "in the language of the question". A chatbot set to one language keeps it.
  - **Answer length** adds one instruction to the system prompt.
  - **Default assistant** preselects the assistant on Home; the user must still be allowed to chat with it.
- **Kept in the browser:** language (cookie) and theme (local storage), as in the account menu.
- **Delete all chats:** removes all of the user's conversations from their list (soft delete, audited). Retention rules still decide when messages are removed for good.
- **Shown but not yet active:**
  - With the agent (ADR 0018–0019): default mode, agent steps, follow-up suggestions.
  - With operations (ADR 0022): keep history, remember preferences, data export. These come with GDPR requests.
