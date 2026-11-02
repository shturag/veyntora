# 0028 · Files attached to a chat question

Status: accepted · 2026-11-02

## Decision

The paperclip in the chat attaches files to the question, so "Summarize this!" works on the file just attached. It no longer uploads to **My files**. My files stays in the Library, for documents people want searched in every chat.

- **Admin switch:** `chat.attachments` in the pipeline spec, set in the pipeline editor's **Chat** section. It is on by default.
- **Where it works:** every chatbot, including general chat (ADR 0025).
- **Limits:**
  - up to 5 files per question and 10 per conversation;
  - 20 MB per file.

## Reading a file

- **When:** the file is scanned with ClamAV and read when it is attached. Only its text is kept, up to 200,000 characters; the original file is not stored.
- **Plain text** (`.txt .md .csv .html`): the API reads it.
- **PDF, Office and images:** these need the chatbot's ingestion parser.
  - The graph server parses them, because it holds the secret reader and the API does not.
  - Without a parser, the chat offers plain text only and says why.
  - The parser is a provider the chatbot already uses, so its data rule already covers it.
- **Scanner:** if scanning is required and no scanner is reachable, attaching is refused.

## Using the text

- **Sources:** the files go with every question in the conversation. They are numbered before any document, and the answer cites them like documents.
- **Grounded chatbots** may answer from a file even when no document matches.
- **General chat** treats them as material the person provided.
- **Question budget:** about 48,000 characters per question, shared between the files. A file cut to fit is marked.
- **Same checks as the question:** the data rule, personal-data masking, and the input and output checks apply.
- **Agent mode:** the files go with the question and are the first sources.
- **Custom flows:** they do not use attachments yet.

## Who sees them, and for how long

- **Who:**
  - A file belongs to the person and the chatbot it was attached for.
  - Once sent, it also belongs to that conversation.
  - The chat proxy and the graph both check this.
- **How long:**
  - Files are deleted with their conversation, so chat retention, deletion and legal holds apply.
  - Files attached but never sent are purged after a day.
  - They are included in the person's data export.
- **Citations:** a citation of a file is stored as `citations.attachment_id`.

## Alternatives

- **Uploading to My files and searching it.** Rejected: the file is only searchable after indexing, the question is not tied to the file, and a chatbot without documents never reads it.
