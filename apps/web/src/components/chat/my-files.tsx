"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { api, CSRF_HEADERS } from "@/lib/chat";

export type MyFile = {
  id: string;
  name: string;
  status: string;
  scan_status: string;
  error: string | null;
};

export const ACCEPT = ".pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.txt,.csv,.png,.jpg,.jpeg,.tif,.tiff";

/** Upload files to "My files". Throws with the API's message on failure. */
export async function uploadMyFiles(files: FileList | File[]): Promise<void> {
  const body = new FormData();
  for (const f of Array.from(files)) body.append("files", f);
  const res = await fetch("/api/v1/me/files", { method: "POST", body, headers: CSRF_HEADERS });
  if (!res.ok) {
    const detail = ((await res.json().catch(() => ({}))) as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : String(res.status));
  }
}

/** "My files" in the Library (prototype: Library.html): private uploads, searched by your chats. */
export function MyFiles({ initial }: { initial: MyFile[] }) {
  const t = useTranslations("myFiles");
  const [files, setFiles] = useState<MyFile[]>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setFiles(await api<MyFile[]>("/v1/me/files"));
    } catch {
      setError(t("loadFailed"));
    }
  }, [t]);

  // While files are being scanned and indexed, check again every few seconds.
  const pending = files.some((f) => f.status === "pending");
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => void load(), 4000);
    return () => clearInterval(timer);
  }, [pending, load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const chosen = input.current?.files;
    if (!chosen?.length) return;
    setBusy(true);
    setError(null);
    try {
      await uploadMyFiles(chosen);
      if (input.current) input.current.value = "";
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("uploadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    await api(`/v1/me/files/${id}`, { method: "DELETE" });
    await load();
  }

  const label = (f: MyFile) =>
    f.scan_status === "infected"
      ? t("infected")
      : f.status === "indexed"
        ? t("ready")
        : f.status === "failed"
          ? t("failed")
          : t("indexing");
  const tone = (f: MyFile) =>
    f.status === "indexed" ? "green" : f.status === "failed" ? "red" : "neutral";

  return (
    <section
      aria-labelledby="my-files"
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
    >
      <h2 id="my-files" className="m-0 text-sm font-semibold">
        {t("title")}
      </h2>
      <p className="m-0 text-xs text-fg-muted">{t("hint")}</p>
      <form onSubmit={submit} className="flex flex-col gap-2">
        <label className="text-[13px] font-medium">
          {t("choose")}
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            className="mt-1 block w-full text-xs"
          />
        </label>
        <div>
          <Button type="submit" size="sm" disabled={busy}>
            {busy ? t("uploading") : t("upload")}
          </Button>
        </div>
      </form>
      {error ? (
        <p role="alert" className="m-0 text-xs text-red">
          {error}
        </p>
      ) : null}
      {files.length > 0 ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {files.map((f) => (
            <li key={f.id} className="flex flex-col gap-1 border-t border-divider pt-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm">{f.name}</span>
                <Badge tone={tone(f)}>{label(f)}</Badge>
              </div>
              {f.error ? <span className="text-xs text-red">{f.error}</span> : null}
              <div>
                <button
                  type="button"
                  onClick={() => remove(f.id)}
                  className="text-xs text-fg-muted underline"
                >
                  {t("remove", { name: f.name })}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-xs text-fg-muted">{t("empty")}</p>
      )}
    </section>
  );
}
