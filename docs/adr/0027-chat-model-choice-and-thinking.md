# 0027 · Model choice and thinking in the chat

Status: accepted · 2026-11-02

## Decision

- **New section `chat` in the pipeline spec (ChatSpec):** what people may switch in the chat.
  - `llm_instance_ids`: the extra models the asker may pick from, up to 12. The answer model (`generation.llm_instance_id`) is always the default and always offered.
  - `thinking`: whether the asker may switch the model's thinking on and off.
- **The admin chooses:** in the **Chat** section of the pipeline editor, or in guided setup for a general chat. A model must be an LLM provider; external ones need the chatbot's data rule, like any other provider used by the chatbot. Publishing checks both.
- **The chat shows only what is offered** (`GET /v1/me/chatbots/{id}/features`):
  - a model picker when there is more than one model;
  - a Thinking switch when it is offered and at least one offered model can think.
- **Each question carries the choice.** The chat proxy always sets `model` and `thinking`, so a conversation never keeps an earlier question's choice. The graph refuses a model the chatbot does not offer.

## Thinking

- **Off unless switched on:** where the switch is offered, no choice means off. Elsewhere the model's own default applies.
- **How a provider switches it:**
  - **Anthropic:** adaptive thinking, with summarized reasoning.
  - **OpenAI-compatible:** the admin sets **Thinking switch** on the provider:
    - `enable_thinking` for SiliconFlow and DashScope;
    - `chat_template_kwargs` for vLLM and SGLang.
  - A provider without a switch is not offered for thinking.
- **What people see:** the reasoning streams in an open panel while the model thinks. It is then kept under the answer as a folded **Thought process**. Masked personal data is unmasked in it exactly as in the answer.

## Answers without documents

For a chatbot with retrieval off (ADR 0025), the chat says so:

- **Composer:** "Ask anything…".
- **Footer:** the answers come from general knowledge and have no sources.
- **AI notice:** the platform's default notice says answers come from company documents, so it is not shown for these chatbots. An admin's own wording is always shown.

## Not yet

Web search and the code interpreter are separate decisions with their own providers and sandbox.
