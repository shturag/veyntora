# 0026 · Presidio as a personal-data detector you connect

Status: accepted · 2026-11-02 · revised the same day: Presidio is not part of the stack

## Decision

- **Adapter:** `presidio`, a guardrail for the **PII slot only**. It calls a Microsoft Presidio analyzer (MIT licence) that you run and operate yourself.
- **Not bundled:** Veyntora does not ship or start Presidio. Add it under **Providers & keys → Add provider → Guardrail → Presidio**.
- **Connection:**
  - **Endpoint:** its base URL; Veyntora calls `/analyze`.
  - **Key:** optional. It is sent as a bearer token, for a Presidio behind a gateway.
  - **Hosting:** declare it like any provider. If you mark it **external**, every chatbot that uses it needs it allowed in its data rule.
- **Why:** it is an alternative to Azure AI Language (PII). Run it in your own network, and personal data is found without another cloud service.

## What Veyntora asks it for

- **Entities:**
  - person, location, e-mail, phone, IBAN, card number, IP address, crypto wallet, medical licence;
  - not dates or URLs, which would garble ordinary answers.
- **Languages:** the question's language is passed for `en` and `de`; others are sent as `en`. Your Presidio must be configured for the languages you use. The official image ships English only; for German, install spaCy's `de_core_news_md` and list `de` in its NLP, analyzer and recognizer configuration.

## Slots are checked by kind

- **PII slot:** Presidio or Azure AI Language (PII).
- **Input and output safety checks:** Llama Guard or Azure AI Language (PII).

A provider of the wrong kind is refused when publishing, and the forms list only the right kinds.
