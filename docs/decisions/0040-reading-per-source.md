# 0040 · Each data source chooses how its documents are read

Status: accepted · 2026-11-10

## Context

How documents were read (parser, OCR, tables, picture descriptions, vision model) was a pipeline setting, so it belonged to each chatbot. A scanned archive and a wiki attached to the same chatbot were read the same way, and the same source was read differently by every chatbot it was attached to. The only reader was Docling. Admins also could not limit a source to some file types, sizes or paths, could not make a website crawl use its sitemap or slow down, and could not re-read everything after changing a setting.

## Decision

**1. Reading is set per source.** A source's config holds `reading` (`veyntora_spec.extraction.SourceReading`):
- **The method:**
  - `auto` (the default for new sources): PDFs whose pages all carry text are read from their text layer, and scans go to the parser with OCR;
  - `text`: only the text layer of PDFs;
  - `layout`: Docling;
  - `vision`: a vision model transcribes every page (ADR 0037).
- **The models and options:** the parser, the vision model, OCR, tables and picture descriptions. Formats other than PDF always go to the parser.
- **What stays in the pipeline:** chunking, embeddings and search remain pipeline settings.

**2. Fast text uses pypdf.** It's a new dependency of the workers (BSD-3-Clause, pinned) and runs in-house. Its pages are cut into passages at paragraphs, to the chunk size, when the pipeline uses structure-aware chunking.

**3. Index profiles take the reading from the source.**
- **The key:** `index_profile(spec, extraction)` builds the profile from the pipeline's chunking and embedding settings plus the source's reading.
- **Existing keys don't change:** the new `reading` field is left out of the key at `layout`, so profiles from before this decision keep their keys and nothing is re-indexed.
- **Search:** a chatbot searches one key per attached source (`RunContext.profile_keys`).
- **Changing the reading:** this gives a new profile; the source is synced and its documents are indexed into it.

**4. Sources without a reading of their own:**
- **Which sources:** sources from before this decision, "My files" and files attached in the chat.
- **How they're read:** as each chatbot's Pipeline → Ingestion says, exactly as before. The source page offers "As each chatbot's pipeline says" next to the four methods.

**5. File filters per source:**
- **What can be limited:** file types, a size limit below the platform's, and glob patterns to include and exclude, matched on the path (with a slash) or the name (without).
- **Connected sources:** a file excluded by the filters counts as not listed, so one read before is removed after a complete listing.
- **SharePoint Online:** its change feed is reset when the filters change, so every file is checked again.
- **Uploads:** a file the filters exclude is refused.

**6. Websites:**
- **Sitemaps:** `use_sitemap` reads the sitemaps that robots.txt names, or `/sitemap.xml`, and follows sitemap indexes. At most 20 sitemaps are read, and only pages on the start pages' hosts and paths are kept. Sitemaps with a DTD are refused.
- **Delay:** `delay_seconds` spaces out requests.

**7. Re-read everything:** queues every document of a source for indexing again, changed or not. It's recorded once in the audit log.

## Consequences

- Each source can use the reader that fits its documents, and digital PDFs no longer need Docling: Auto is much faster for them.
- Two places decide reading: the source, or for sources without a setting, the pipeline. The source page says which applies.
- Chunks indexed under a profile no longer used stay in the vector store until the document is removed, as with pipeline changes before. Search ignores them.
- Gzip-compressed sitemaps (`.xml.gz`) aren't read yet.
