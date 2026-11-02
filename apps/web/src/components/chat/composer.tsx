"use client";

import { Button, cn } from "@veyntora/ui";
import { FileText, Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { MODES, attachFile, type AttachedFile, type Mode } from "@/lib/chat";

// Files a question may bring (the API's limit).
const MAX_FILES = 5;

/**
 * Question box with the answer-mode switch (prototype: Home.html, ChatFast.html). Auto lets
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
  /** More controls next to the mode switch (model picker, thinking). */
  extras?: ReactNode;
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
      className="flex flex-col gap-3 rounded-xl border border-line-strong bg-surface p-3.5 shadow-[0_2px_10px_rgba(11,16,51,0.06)]"
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
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          {attach ? (
            <>
              <Button
                type="button"
                size="lg"
                className="w-11 px-0"
                aria-label={t("attach")}
                title={t("attachHint", { types: attach.accept.join(" ") })}
                disabled={attaching || files.length >= MAX_FILES}
                onClick={() => fileInput.current?.click()}
              >
                <Paperclip aria-hidden className="size-4" />
              </Button>
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
          <div
            role="radiogroup"
            aria-label={t("mode")}
            className="flex gap-0.5 rounded-md bg-sunken p-[3px]"
          >
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => onModeChange(m)}
                className={cn(
                  "rounded-[8px] px-3 py-1.5 text-[13px]",
                  mode === m ? "bg-surface font-medium text-fg shadow-sm" : "text-fg-muted",
                )}
              >
                {t(`modes.${m}`)}
              </button>
            ))}
          </div>
          {extras}
        </div>
        <Button type="submit" variant="primary" size="lg" disabled={!ready}>
          {busy ? t("answering") : (submitLabel ?? t("ask"))}
        </Button>
      </div>
      {attachError ? (
        <p role="alert" className="m-0 text-xs text-red">
          {attachError}
        </p>
      ) : null}
    </form>
  );
}
