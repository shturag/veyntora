# 0018 · German compound splitting from the documents' vocabulary

Status: accepted · 2026-10-31

## Decision (product owner)

No library and no word list. Words are split using the vocabulary of the chatbot's own indexed documents.

- **Why not a library:** no small, permissively licensed decompounder is published on PyPI.
  - CharSplit is MIT-licensed but unpublished since 2020, and it carries a 40 MB table. Its PyPI name belongs to an unrelated package.
  - `compound-split` is GPL-3.0.
  - `compound-word-splitter` needs system spell-checker dictionaries.

## How it works (`veyntora_api.knowledge.vocabulary`)

- **Vocabulary:** `index_terms` counts, per index profile, in how many documents each word of 4–64 letters occurs. It counts the indexed text and the headings.
  - `document_indexes.terms` keeps each document's words, so that re-indexing or removing a document updates the counts.
  - A reversed-term index turns "compounds ending in X" into a prefix lookup.
- **At query time,** with *German compound splitting* on and keyword search in use, the BM25 query gets extra terms in two directions. The dense query is unchanged.
  - **Parts:** words of 8+ letters are split into 2–3 parts that the documents use. The German linking letters -s-, -es-, -n-, -en- and -e- are allowed. The split is frequency-based (Koehn & Knight, 2003): it is kept only if the geometric mean of the parts' counts beats the whole word's count. Parts are never invented.
  - **Head nouns:** up to 3 of the most frequent compounds that end in a word of the question are added ("Richtlinie" → "Rückerstattungsrichtlinie").
- **No index change:** expansion happens at query time only, so switching the toggle needs no re-index.

## Limits

- **Existing documents:** they enter the vocabulary when they are next indexed. A full source re-sync fills it.
- **Removing a whole source:** its documents' index rows are deleted by cascade, so their counts can stay too high. That only adds harmless extra terms.
- **Privacy:** the vocabulary is per profile, not per user. Extra terms only steer the keyword match. Results are always filtered by the user's permissions, and the terms are never shown or returned.
