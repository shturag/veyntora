"use client";

import { cn } from "@veyntora/ui";
import { ArrowUp, FileText, Loader2, Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { MODES, attachFile, type AttachedFile, type Mode } from "@/lib/chat";

/** The toolbar's controls: one height, quiet outline. */
export const CONTROL =
  "inline-flex h-8 items-center gap-1.5 rounded-full border border-line-strong px-3 text-[13px] text-fg-muted transition-colors hover:text-fg disabled:opacity-40";

// Files a question may bring (the API's limit).
const MAX_FILES = 5;

/**
 * Question box with the answer-mode switch. Auto lets
 * the router choose; the chatbot's pipeline may allow fewer modes (the server falls back).
 */
export function Composer({
  onSubmit,
  mode,
  onModeChange,
  busy = false,
  disabled = false,
  rows = 3,
  autoFocus = false,
  submitLabel,
  extras,
  trailing,
  placeholder,
  attach,
}: {
  onSubmit: (question: string, files: AttachedFile[]) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  busy?: boolean;
  disabled?: boolean;
  rows?: number;
  autoFocus?: boolean;
  submitLabel?: string;
  /** Tools next to the paperclip (thinking, integrations). */
  extras?: ReactNode;
  /** Settings next to the mode switch (the model picker). */
  trailing?: ReactNode;
  placeholder?: string;
  /** The chatbot that takes attached files, and the endings it reads; none: no paperclip. */
  attach?: { chatbotId: string; accept: string[] } | null;
}) {
  const t = useTranslations("chat");
  const [text, setText] = useState("");
  const id = useId();
  const [files, setFiles] = useState<AttachedFile[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const ready = text.trim().length > 0 && !busy && !disabled && !attaching;

  // Each file is scanned and read now; its text goes with this question and the rest of
  // the conversation.
  async function addFiles(el: HTMLInputElement) {
    const picked = Array.from(el.files ?? []);
    el.value = "";
    if (!attach || !picked.length) return;
    setAttachError(null);
    if (files.length + picked.length > MAX_FILES) {
      setAttachError(t("attachTooMany", { max: MAX_FILES }));
      return;
    }
    setAttaching(true);
    try {
      for (const f of picked) {
        const added = await attachFile(attach.chatbotId, f);
        setFiles((list) => [...list, added]);
      }
    } catch (e) {
      setAttachError(e instanceof Error ? e.message : t("attachFailed"));
    } finally {
      setAttaching(false);
    }
  }

  function send(event?: FormEvent) {
    event?.preventDefault();
    if (!ready) return;
    onSubmit(text.trim(), files);
    setText("");
    setFiles([]);
    setAttachError(null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) send(event);
  }

  return (
    <form
      onSubmit={send}
      className="flex flex-col gap-2 rounded-2xl border border-line-strong bg-surface px-3.5 pt-3 pb-2.5 shadow-[0_2px_10px_rgba(11,16,51,0.06)] focus-within:border-accent"
    >
      <label htmlFor={id} className="sr-only">
        {t("askLabel")}
      </label>
      <textarea
        id={id}
        rows={rows}
        value={text}
        maxLength={8000}
        autoFocus={autoFocus}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder ?? t("placeholder")}
        className="resize-none border-0 bg-transparent text-base text-fg outline-none placeholder:text-fg-muted"
      />
      {files.length || attaching ? (
        <ul aria-label={t("attachedFiles")} className="m-0 flex list-none flex-wrap gap-2 p-0">
          {files.map((f) => (
            <li
              key={f.id}
              className="inline-flex max-w-[260px] items-center gap-1.5 rounded-md border border-line bg-sunken py-1 pr-1 pl-2 text-[13px]"
            >
              <FileText aria-hidden className="size-3.5 shrink-0 text-fg-muted" />
              <span className="truncate" title={f.name}>
                {f.name}
              </span>
              {f.truncated ? <span className="text-fg-muted">· {t("attachCut")}</span> : null}
              <button
                type="button"
                aria-label={t("attachRemove", { name: f.name })}
                onClick={() => setFiles((list) => list.filter((x) => x.id !== f.id))}
                className="rounded p-0.5 text-fg-muted hover:text-fg"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </li>
          ))}
          {attaching ? (
            <li role="status" className="py-1 text-[13px] text-fg-muted">
              {t("attaching")}
            </li>
          ) : null}
        </ul>
      ) : null}
      {/* One compact toolbar: tools on the left, model, mode and send on the right. */}
      <div className="flex flex-wrap items-center gap-1.5">
        {attach ? (
          <>
            <button
              type="button"
              className={cn(CONTROL, "w-8 justify-center px-0")}
              aria-label={t("attach")}
              title={t("attachHint", { types: attach.accept.join(" ") })}
              disabled={attaching || files.length >= MAX_FILES}
              onClick={() => fileInput.current?.click()}
            >
              <Paperclip aria-hidden className="size-4" />
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={attach.accept.join(",")}
              className="hidden"
              tabIndex={-1}
              aria-hidden
              onChange={(e) => void addFiles(e.currentTarget)}
            />
          </>
        ) : null}
        {extras}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
          {trailing}
          <div
            role="radiogroup"
            aria-label={t("mode")}
            className="flex h-8 items-center gap-0.5 rounded-full bg-sunken p-0.5"
          >
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => onModeChange(m)}
                className={cn(
                  "h-7 rounded-full px-2.5 text-xs",
                  mode === m
                    ? "bg-surface font-medium text-fg shadow-sm"
                    : "text-fg-muted hover:text-fg",
                )}
              >
                {t(`modes.${m}`)}
              </button>
            ))}
          </div>
          <button
            type="submit"
            disabled={!ready}
            aria-label={busy ? t("answering") : (submitLabel ?? t("ask"))}
            title={busy ? t("answering") : (submitLabel ?? t("ask"))}
            className="inline-flex size-9 items-center justify-center rounded-full bg-accent text-on-accent transition-opacity disabled:opacity-40"
          >
            {busy ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <ArrowUp aria-hidden className="size-4" />
            )}
          </button>
        </div>
      </div>
      {attachError ? (
        <p role="alert" className="m-0 text-xs text-red">
          {attachError}
        </p>
      ) : null}
    </form>
  );
}
