"use client";

import { Button, cn } from "@veyntora/ui";
import { Paperclip } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { MODES, type Mode } from "@/lib/chat";

import { ACCEPT, uploadMyFiles } from "./my-files";

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
}: {
  onSubmit: (question: string) => void;
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
}) {
  const t = useTranslations("chat");
  const [text, setText] = useState("");
  const id = useId();
  const ready = text.trim().length > 0 && !busy && !disabled;
  const fileInput = useRef<HTMLInputElement>(null);
  const [attaching, setAttaching] = useState(false);
  const [attachNote, setAttachNote] = useState<{ ok: boolean; text: string } | null>(null);

  // Attached files go to "My files": private to you and searched by your chats once indexed.
  async function attach(el: HTMLInputElement) {
    if (!el.files?.length) return;
    setAttaching(true);
    setAttachNote(null);
    try {
      await uploadMyFiles(el.files);
      setAttachNote({ ok: true, text: t("attached", { count: el.files.length }) });
    } catch (e) {
      setAttachNote({ ok: false, text: e instanceof Error ? e.message : t("attachFailed") });
    } finally {
      el.value = "";
      setAttaching(false);
    }
  }

  function send(event?: FormEvent) {
    event?.preventDefault();
    if (!ready) return;
    onSubmit(text.trim());
    setText("");
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
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="lg"
            className="w-11 px-0"
            aria-label={t("attach")}
            disabled={attaching}
            onClick={() => fileInput.current?.click()}
          >
            <Paperclip aria-hidden className="size-4" />
          </Button>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => void attach(e.currentTarget)}
          />
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
      {attachNote ? (
        <p
          role={attachNote.ok ? "status" : "alert"}
          className={cn("m-0 text-xs", attachNote.ok ? "text-fg-muted" : "text-red")}
        >
          {attachNote.text}
        </p>
      ) : null}
    </form>
  );
}
