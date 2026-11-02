# 0026 · Presidio: finding personal data inside the network

Status: accepted · 2026-11-02

## Decision

- **Adapter:** `presidio`, a guardrail for the **PII slot only**. It calls a self-hosted Microsoft Presidio analyzer (MIT licence).
- **Why:** before this, the only personal-data detector was Azure AI Language. That is an external service, so protecting data from one external model meant sending it to another.
- **Image:** `mcr.microsoft.com/presidio-analyzer:2.2.362` (2026-03-15, amd64 and arm64), extended in `deploy/compose/presidio`:
  - adds spaCy's `de_core_news_md` 3.8.0, pinned by URL, next to the bundled `en_core_web_lg`;
  - sets the configuration to English and German.
- **Optional in compose:** add `bundled-presidio` to `COMPOSE_PROFILES`. It runs on port 5002 locally and `http://presidio:3000` inside the stack.

## What it finds

- **Recognised:** names and places (from the language models), e-mail, phone, IBAN, card numbers, IP addresses, crypto wallets and medical licences.
- **Deliberately left out:** dates, URLs and organisations. They are rarely personal, and masking them would garble ordinary answers.
- **Missed:** street addresses (for example "Hauptstraße 5"). Azure AI Language finds those.
- **Languages:** questions in other languages are analysed as English.

## Slots are checked by kind

- **PII slot:** Presidio or Azure AI Language (PII).
- **Input and output safety checks:** Llama Guard or Azure AI Language (PII).

A provider of the wrong kind is refused when publishing, and the forms list only the right kinds.
