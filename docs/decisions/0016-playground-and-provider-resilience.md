# 0016 · Playground and provider resilience

Status: accepted · 2026-10-31

## Playground

- **Where it runs:** only runtime services may read provider keys (ADR 0004). So a test run is a stateless run of a new `playground` graph on the graph server, with the tester's own token. The API (`POST /v1/admin/playground/run`) runs the draft and the live version at the same time and returns both.
- **Who may test:** anyone with `can_edit_draft` on the chatbot, the same right that edits its pipeline. The chatbot doesn't need to be live. The graph checks this again from the token.
- **Whose permissions:** retrieval uses the tester's own permissions, so a test never shows a document the tester couldn't open. Testing "as another user" is not offered. It touches permissions and needs a product decision.
- **What is kept:** no conversation is stored. Model usage is recorded, since tests cost money too. The audit log gets one entry per run, with the versions and outcomes but not the question text.
- **Step by step:** a `Trace` can keep its steps in memory (`collect=True`): name, duration, and the attributes the step already sends to Langfuse. The Playground shows these, so it and Langfuse never disagree about a run.
- **Failures:** a provider error ends that column with "Failed" and the adapter's status-only message. The other column still runs.
- **Mode:** Fast only. Agent and Auto are shown disabled until the agent (ADR 0018–0019).

## Replacing a key with a grace period (product owner: choosable, 24 h default)

- **Storage:** OpenBao KV v2 keeps earlier versions. When a key is replaced, the row records the replaced version (`kv/providers/{id}?version=N`) and when its grace period ends. The choices are now, 1 h, 24 h (default) and 7 days.
- **Use:** the replaced key is tried only when the new one is rejected (`KeyRejectedError`, HTTP 401/403 or the Anthropic auth errors). The retry happens once, and only before the call produced output.
- **One old key at most:** replacing the key again destroys the version that is still in its grace period. "Now" destroys the replaced version at once.
- **Cleanup:** the API, the only service that may write to OpenBao, destroys expired versions every hour.
- **What is shown:** the UI shows until when the old key is still tried. The API never returns the reference or the version.

## Fallback instances and disabling

- **Rules for a fallback:** it must offer the same capability, and it may not loop back to the instance (checked on save; the runtime follows at most 3 fallbacks).
- **When it is used:** when a call fails before producing any output, and in place of the instance while that instance is disabled.
- **Disabling:** an instance used by any draft, live or canary pipeline can only be disabled once an enabled fallback is set. A fallback that stands in for a disabled instance can't be disabled or removed either.
- **Data rules cover fallbacks:** publishing and every run check the fallback chain against the chatbot's allowed external providers. An answer is marked external if the instance *or a fallback it may use* is external. This is reported on the safe side: it may say "external" when the fallback wasn't needed.
- **The rerank fallback in the pipeline spec** stays. It is a pipeline choice; this one is a provider property.

## Usage and cost per instance

- **Where it is recorded:** the existing `usage_records` table gets one row per model call (answer generation, question rewrite), for chat and Playground runs.
- **Attribution:** each row names the instance that actually served the call (its fallback when it fell back or is disabled).
- **Cost:** the prices set on the instance (options `price_in_per_mtok_eur` and `price_out_per_mtok_eur`, EUR per million tokens) at the time of the call. Instances without prices count tokens at cost 0.
- **Not counted yet:** embedding, rerank and guardrail calls report no token usage through the adapters. That is open for the Usage & budgets screen (ADR 0021).
