"use client";

import { cn } from "@veyntora/ui";
import { Eye, FileText, LayoutTemplate, Sparkles, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { components } from "@/lib/api/schema";

import { inputClass, labelClass } from "./source-forms";

export type SourceReading = components["schemas"]["SourceReading"];
export type ReaderOption = components["schemas"]["ReaderOption"];
type Method = components["schemas"]["ExtractionMethod"];
// "pipeline": no setting of its own; read as each chatbot's pipeline says (older sources).
type Choice = Method | "pipeline";

// The file types Veyntora reads (knowledge.service.UPLOAD_TYPES).
const FILE_TYPES = [
  "pdf",
  "docx",
  "pptx",
  "xlsx",
  "html",
  "md",
  "txt",
  "csv",
  "png",
  "jpg",
  "tiff",
];
// Types with a second extension: choosing one chooses both.
const ALIASES: Record<string, string> = { html: "htm", jpg: "jpeg", tiff: "tif" };
const METHODS: { key: Choice; icon: typeof Sparkles }[] = [
  { key: "auto", icon: Sparkles },
  { key: "text", icon: FileText },
  { key: "layout", icon: LayoutTemplate },
  { key: "vision", icon: Eye },
];
const area = "rounded-md border border-line-strong bg-surface p-3 font-mono text-sm font-normal";
const lines = (v: FormDataEntryValue | null) =>
  String(v || "")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

/** How a source reads its documents: the method, parser, vision model and options. */
export function ReadingFields({
  options,
  value,
  allowPipeline = false,
}: {
  options: ReaderOption[];
  value?: SourceReading;
  /** Offer "as each chatbot's pipeline says" (sources from before reading per source). */
  allowPipeline?: boolean;
}) {
  const t = useTranslations("sources.reading");
  const ex = value?.extraction ?? null;
  const [method, setMethod] = useState<Choice>(ex?.method ?? (allowPipeline ? "pipeline" : "auto"));
  const parsers = options.filter((o) => o.capability === "parser" && o.enabled);
  const visions = options.filter((o) => o.capability === "vision" && o.enabled);
  const choices = allowPipeline
    ? [...METHODS, { key: "pipeline" as const, icon: Workflow }]
    : METHODS;
  const own = method !== "pipeline";

  return (
    <>
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-1.5 text-[13px] font-medium">{t("method")}</legend>
        <div className="grid grid-cols-2 gap-2 max-[760px]:grid-cols-1">
          {choices.map(({ key, icon: Icon }) => (
            <label
              key={key}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-md border px-3.5 py-3 text-sm transition-colors",
                method === key
                  ? "border-accent bg-accent-soft/40 ring-1 ring-accent"
                  : "border-line hover:bg-sunken/50",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent",
              )}
            >
              <input
                type="radio"
                name="read_method"
                value={key}
                checked={method === key}
                onChange={() => setMethod(key)}
                className="sr-only"
              />
              <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="font-medium">{t(`methods.${key}`)}</span>
                <span className="text-xs text-fg-muted">{t(`methodHints.${key}`)}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {own ? (
        <>
          <div className="grid grid-cols-2 gap-3 max-[760px]:grid-cols-1">
            <label className={labelClass}>
              {t("parser")}
              <select
                name="read_parser"
                required
                defaultValue={ex?.parser_instance_id ?? parsers[0]?.id ?? ""}
                className={inputClass}
              >
                {parsers.length ? null : <option value="">{t("noParser")}</option>}
                {parsers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.external ? ` · ${t("external")}` : ""}
                  </option>
                ))}
              </select>
              <span className="text-xs font-normal text-fg-muted">{t("parserHint")}</span>
            </label>
            <label className={labelClass}>
              {t("vision")}
              <select
                name="read_vision"
                required={method === "vision"}
                defaultValue={ex?.vision_instance_id ?? ""}
                className={inputClass}
              >
                <option value="">{t("none")}</option>
                {visions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.external ? ` · ${t("external")}` : ""}
                  </option>
                ))}
              </select>
              <span className="text-xs font-normal text-fg-muted">{t("visionHint")}</span>
            </label>
          </div>
          <div className="flex flex-col divide-y divide-line rounded-md border border-line">
            {(["ocr", "extract_tables", "describe_images"] as const).map((k) => (
              <label
                key={k}
                className="flex cursor-pointer items-start gap-3 px-4 py-3 text-sm hover:bg-sunken/50"
              >
                <input
                  type="checkbox"
                  name={`read_${k}`}
                  defaultChecked={ex ? Boolean(ex[k]) : k !== "describe_images"}
                  className="mt-0.5 size-4 shrink-0"
                />
                <span className="flex flex-col gap-0.5">
                  <span className="font-medium">{t(`options.${k}`)}</span>
                  <span className="text-xs text-fg-muted">{t(`optionHints.${k}`)}</span>
                </span>
              </label>
            ))}
          </div>
        </>
      ) : (
        <p className="m-0 rounded-md bg-sunken px-3 py-2.5 text-sm text-fg-secondary">
          {t("pipelineNote")}
        </p>
      )}
    </>
  );
}

/** Which of the source's files are read: types, size and path patterns. */
export function FileFilterFields({ value }: { value?: SourceReading }) {
  const t = useTranslations("sources.reading");
  const f = value?.filters;
  const chosen = new Set(f?.file_types ?? []);
  return (
    <>
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1.5 text-[13px] font-medium">{t("fileTypes")}</legend>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2">
          {FILE_TYPES.map((x) => (
            <label
              key={x}
              className="flex cursor-pointer items-center gap-2 rounded-md border border-line px-3 py-2 font-mono text-[13px] hover:bg-sunken/50"
            >
              <input
                type="checkbox"
                name="read_types"
                value={x}
                defaultChecked={chosen.has(x)}
                className="size-4 shrink-0"
              />
              .{x}
            </label>
          ))}
        </div>
        <span className="text-xs text-fg-muted">{t("fileTypesHint")}</span>
      </fieldset>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] items-start gap-3">
        <label className={labelClass}>
          {t("maxSize")}
          <input
            name="read_max_mb"
            type="number"
            min={1}
            max={2048}
            defaultValue={f?.max_file_mb ?? ""}
            placeholder={t("maxSizePlaceholder")}
            className={inputClass}
          />
        </label>
        <label className={labelClass}>
          {t("include")}
          <textarea
            name="read_include"
            rows={2}
            defaultValue={(f?.include ?? []).join("\n")}
            placeholder="/policies/*"
            className={area}
          />
        </label>
        <label className={labelClass}>
          {t("exclude")}
          <textarea
            name="read_exclude"
            rows={2}
            defaultValue={(f?.exclude ?? []).join("\n")}
            placeholder={"*/archive/*\n*.tmp"}
            className={area}
          />
        </label>
      </div>
      <span className="text-xs text-fg-muted">{t("patternsHint")}</span>
    </>
  );
}

/** The reading settings the two field groups above hold. */
export function readingFrom(form: FormData): SourceReading {
  const method = String(form.get("read_method") || "pipeline") as Choice;
  const maxMb = Number(form.get("read_max_mb")) || null;
  return {
    extraction:
      method === "pipeline"
        ? null
        : {
            method,
            parser_instance_id: String(form.get("read_parser") || "") || null,
            vision_instance_id: String(form.get("read_vision") || "") || null,
            ocr: form.get("read_ocr") === "on",
            extract_tables: form.get("read_extract_tables") === "on",
            describe_images: form.get("read_describe_images") === "on",
          },
    filters: {
      file_types: form
        .getAll("read_types")
        .map(String)
        .flatMap((x) => (ALIASES[x] ? [x, ALIASES[x]] : [x])),
      max_file_mb: maxMb,
      include: lines(form.get("read_include")),
      exclude: lines(form.get("read_exclude")),
    },
  };
}
