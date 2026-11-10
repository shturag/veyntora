# 0030 · Code interpreter: a sandbox in the stack

Status: accepted · 2026-11-02

## Decision

- **New service:** `sandbox` (`services/sandbox`) runs Python for the chat. It is a small HTTP server built on the standard library.
- **Provider kind:** `code_interpreter`, adapter `sandbox`. An admin adds it under **Providers & keys → Add provider → Code interpreter** with endpoint `http://sandbox:8090`.
- **Admin choice:** the admin picks it for a chatbot in the pipeline editor's **Chat** section (`chat.code_instance_id`).
- **People's choice:** they switch it on per question under **Integrations**.
- **The tool:** the answer model gets one tool, `run_python`. It may call it up to 4 times per answer, sees the printed output, then answers.
- **Shown to people:** the code and its output are folded under the answer; charts are shown.
- **Data:** the sandbox is self-hosted, so code and data stay in-house. The data rule's masking still applies to what the external model sees.

## Isolation

- **Network:**
  - The sandbox sits only on the Docker network `sandbox`, which is `internal: true`, so it has no route to the internet.
  - Only the graph server, and the workers for **Test connection**, join that network. The API and the other services cannot reach it.
- **Container:**
  - read-only file system, and a 256 MB `/tmp` in memory;
  - all Linux capabilities dropped, `no-new-privileges`;
  - runs as user `nobody`;
  - 1 CPU, 1 GB of memory, 128 processes.
- **Per run:**
  - A new `python -I` process, in its own session and its own empty folder.
  - The folder is deleted afterwards, so nothing is kept between runs.
  - The environment is empty: no keys or tokens.
  - Limits: 20 s of CPU, 30 s of wall time (the whole process group is killed), 768 MB of memory, 20 MB per file, 32 processes.
  - At most 2 runs at a time.
- **Logging:** neither the code nor its output is logged.
- **Libraries:** pinned `numpy` 2.2.6, `pandas` 2.2.3 and `matplotlib` 3.10.3. Nothing is installed at run time.
- **Optional token:** if `SANDBOX_TOKEN` is set, callers must send it. Store the same value as the provider's key.

## Output

- **To the model:** stdout and stderr, up to 4,000 characters each, plus the names of the files written.
- **To the answer:** up to 3 images, each up to 700 KB, plus the code and its output, with personal data put back for the person.
- **Records:** the runs are kept with the answer in the conversation, not in the database's citations.

## Limits

- **Document chatbots:** numbers computed in the sandbox are not sources, so a strict groundedness setting may flag such answers.
- **Not yet:** agent mode and custom flows do not offer the tool.
- **Attached files:** they reach the code only through the model, which sees their text; files are not copied into the sandbox.
