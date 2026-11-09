# 0039 · Small talk gets a labelled reply

Status: accepted · 2026-11-10

## Context

A chatbot answers only from its documents ("grounded or silent"). Greetings and questions about the chatbot itself ("hi", "how are you?", "what can you do?") match no passage, so the model was never called and people got "I couldn't find this in the documents you have access to", with an "Ask an expert" button. Such questions reached expert teams, and people could not tell whether the chatbot was working.

A system prompt cannot change this: the model is not called when nothing is found, the fixed rules forbid outside knowledge, and the groundedness check blocks unsupported text.

## Decision

**1. A per-chatbot setting, off by default.** `generation.small_talk` (Pipeline → Generation, "Reply to small talk"). Like every pipeline setting it is part of the draft and takes effect when published, for new and existing chatbots.

**2. Only when nothing was found.** It runs only where the answer would be "no answer": no passage passed reranking, or the model replied `NO_ANSWER`. Questions answered from the documents are unchanged.

**3. One call, narrow rules.** The chatbot's answer model gets the message with no sources and rules that:
- allow a reply of one to three sentences only to small talk or questions about the chatbot;
- describe the chatbot from its name and description only, and forbid facts about any subject, the company or the world;
- require `NO_ANSWER` for anything else, which keeps the no-answer reply and "Ask an expert".

Input checks and masking have already run; the output check still applies. The model is the one the chatbot already uses, so its data rule covers the call; no new provider is involved.

**4. Always labelled.** The reply is marked `small_talk` (and `no_sources`): the chat shows "Small talk, not from the documents" with a "Small talk" badge, the Playground shows a "Small talk" badge, and the message is recorded with the reason "small talk". It cites nothing and has no groundedness score.

## Consequences

- Greetings and "what can you do?" get a friendly reply instead of a dead end, and stop reaching experts.
- Answers from documents stay grounded or silent; a reply that is not grounded is always visibly marked.
- A message that finds nothing costs one more small model call when the setting is on.
- The quality of the reply depends on the chatbot's description: a clear one-line description gives a better "what can you do?" reply.
