"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/chat";

import { RunNow } from "./list-actions";
import { RulesEditor } from "./rules-editor";
import {
  area,
  control,
  errorText,
  field,
  fieldsBefore,
  linesOf,
  newStep,
  objectOf,
  saveSpec,
  stepHref,
  type Automation,
  type Option,
  type Options,
  type Spec,
  type Step,
  type StepType,
} from "./spec";

type Of<K extends StepType> = Extract<Step, { type: K }>;

function Fields({ fields }: { fields: string[] }) {
  const t = useTranslations("automations");
  return (
    <p className="m-0 text-xs text-fg-muted">
      {t("availableFields")} <span className="font-mono">{fields.join(" · ")}</span>
    </p>
  );
}

function AgentFields({
  step,
  set,
  options,
  fields,
}: {
  step: Of<"agent">;
  set: (s: Step) => void;
  options: Options;
  fields: string[];
}) {
  const t = useTranslations("automations");
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("usePipeline")}
          <select
            value={step.chatbot_id ?? ""}
            onChange={(e) => set({ ...step, chatbot_id: e.target.value || null })}
            className={control}
          >
            <option value="">{t("choose")}</option>
            {options.chatbots.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} · {b.detail}
              </option>
            ))}
          </select>
        </label>
        <label className={field}>
          {t("maxSteps")}
          <input
            type="number"
            min={1}
            max={20}
            value={step.max_steps}
            onChange={(e) => set({ ...step, max_steps: Number(e.target.value) || 1 })}
            className={control}
          />
        </label>
      </div>
      <label className={field}>
        {t("task")}
        <textarea
          value={step.task}
          onChange={(e) => set({ ...step, task: e.target.value })}
          className={`${area} min-h-[160px] font-sans text-sm`}
        />
      </label>
      <Fields fields={fields} />
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("stepTools")}</legend>
        {options.tools.length === 0 ? (
          <span className="text-xs text-fg-muted">{t("noTools")}</span>
        ) : null}
        <span className="text-xs text-fg-muted">{t("searchAlways")}</span>
        {options.tools.map((tool) => (
          <label key={tool.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={step.tool_ids.includes(tool.id)}
              onChange={(e) =>
                set({
                  ...step,
                  tool_ids: e.target.checked
                    ? [...step.tool_ids, tool.id]
                    : step.tool_ids.filter((x) => x !== tool.id),
                })
              }
              className="size-4"
            />
            <span className="font-mono">{tool.name}</span>
            <span className="text-xs text-fg-muted">
              {tool.detail} · {t(`access.${tool.access}`)}
            </span>
          </label>
        ))}
      </fieldset>
      <label className={field}>
        {t("outputs")}
        <input
          value={step.outputs.join(", ")}
          onChange={(e) =>
            set({
              ...step,
              outputs: e.target.value
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            })
          }
          placeholder="category, draft_note, confidence"
          className={`${control} font-mono`}
        />
        <span className="text-xs font-normal text-fg-muted">{t("outputsHint")}</span>
      </label>
    </div>
  );
}

function ConditionFields({
  step,
  set,
  spec,
  fields,
}: {
  step: Of<"condition">;
  set: (s: Step) => void;
  spec: Spec;
  fields: string[];
}) {
  const t = useTranslations("automations");
  const later = spec.steps.slice(spec.steps.findIndex((s) => s.id === step.id) + 1);
  const target = (value: string | null, onChange: (v: string | null) => void, label: string) => (
    <label className={field}>
      {label}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className={control}
      >
        <option value="">{t("nextStep")}</option>
        {later.map((s) => (
          <option key={s.id} value={s.id}>
            {s.id} · {s.name || t(`stepTypes.${s.type}`)}
          </option>
        ))}
        <option value="end">{t("endRun")}</option>
      </select>
    </label>
  );
  return (
    <div className="flex flex-col gap-4">
      <RulesEditor
        label={t("continueWhen")}
        rules={step.rules}
        onChange={(rules) => set({ ...step, rules })}
        fields={fields}
        min={1}
      />
      <fieldset className="m-0 flex gap-4 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("join")}</legend>
        {(["and", "or"] as const).map((j) => (
          <label key={j} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="join"
              checked={step.join === j}
              onChange={() => set({ ...step, join: j })}
              className="size-4"
            />
            {t(`joins.${j}`)}
          </label>
        ))}
      </fieldset>
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        {target(step.yes, (yes) => set({ ...step, yes }), t("yesGoTo"))}
        {target(step.no, (no) => set({ ...step, no }), t("noGoTo"))}
      </div>
    </div>
  );
}

function ToolFields({
  step,
  set,
  options,
  fields,
}: {
  step: Of<"tool">;
  set: (s: Step) => void;
  options: Options;
  fields: string[];
}) {
  const t = useTranslations("automations");
  const tool = options.tools.find((x) => x.id === step.tool_id);
  return (
    <div className="flex flex-col gap-4">
      <label className={field}>
        {t("tool")}
        <select
          value={step.tool_id ?? ""}
          onChange={(e) => set({ ...step, tool_id: e.target.value || null })}
          className={control}
        >
          <option value="">{t("choose")}</option>
          {options.tools.map((x) => (
            <option key={x.id} value={x.id}>
              {x.detail} · {x.name} ({t(`access.${x.access}`)})
            </option>
          ))}
        </select>
        {tool && tool.access !== "read" ? (
          <span className="text-xs font-normal text-amber">{t("writeNeedsApproval")}</span>
        ) : null}
      </label>
      <label className={field}>
        {t("toolArguments")}
        <textarea
          defaultValue={linesOf(step.arguments)}
          onChange={(e) => set({ ...step, arguments: objectOf(e.target.value) })}
          placeholder="comment={step2.draft_note}"
          className={area}
        />
        <span className="text-xs font-normal text-fg-muted">{t("argumentsHint")}</span>
      </label>
      <Fields fields={fields} />
    </div>
  );
}

function Recipients({
  value,
  onChange,
  email,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  email: boolean;
}) {
  const t = useTranslations("automations");
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Option[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  // People saved earlier are stored by id: look up their names to show them.
  const unnamed = value.filter((v) => /^[0-9a-f-]{36}$/.test(v) && !(v in names));
  const lookup = unnamed.join(",");
  useEffect(() => {
    if (!lookup) return;
    const query = lookup
      .split(",")
      .map((id) => `ids=${id}`)
      .join("&");
    api<Option[]>(`/v1/admin/automations/people?${query}`)
      .then((people) =>
        setNames((n) => ({ ...n, ...Object.fromEntries(people.map((p) => [p.id, p.name])) })),
      )
      .catch(() => {});
  }, [lookup]);
  useEffect(() => {
    if (q.trim().length < 2) return;
    const timer = setTimeout(() => {
      api<Option[]>(`/v1/admin/automations/people?q=${encodeURIComponent(q.trim())}`)
        .then(setFound)
        .catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [q]);
  return (
    <div className={field}>
      {t("to")}
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {value.map((v) => (
          <li
            key={v}
            className="flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 text-xs font-normal"
          >
            {names[v] ?? v}
            <button
              type="button"
              aria-label={t("removeRecipient", { name: names[v] ?? v })}
              onClick={() => onChange(value.filter((x) => x !== v))}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (email && e.key === "Enter" && q.includes("@")) {
            e.preventDefault();
            onChange([...new Set([...value, q.trim()])]);
            setQ("");
          }
        }}
        placeholder={email ? t("searchOrEmail") : t("searchPeople")}
        className={control}
      />
      {found.length && q.trim().length >= 2 ? (
        <ul className="m-0 flex list-none flex-col rounded-md border border-line p-0 font-normal">
          {found.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="w-full px-3 py-1.5 text-left text-sm hover:bg-sunken"
                onClick={() => {
                  setNames({ ...names, [p.id]: p.name });
                  onChange([...new Set([...value, p.id])]);
                  setQ("");
                  setFound([]);
                }}
              >
                {p.name} <span className="text-xs text-fg-muted">{p.detail}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function NotifyFields({
  step,
  set,
  options,
  fields,
}: {
  step: Of<"notify">;
  set: (s: Step) => void;
  options: Options;
  fields: string[];
}) {
  const t = useTranslations("automations");
  const post = step.channel === "teams_channel" || step.channel === "slack_channel";
  const kind = step.channel === "slack_channel" ? "slack_channel" : "teams_channel";
  return (
    <div className="flex flex-col gap-4">
      <fieldset className="m-0 flex flex-wrap gap-3 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("channel")}</legend>
        {(["teams_chat", "teams_channel", "slack_channel", "email"] as const).map((c) => (
          <label key={c} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`channel-${step.id}`}
              checked={step.channel === c}
              disabled={c === "email" && !options.mail_ready}
              onChange={() => set({ ...step, channel: c, destination_id: null, to: [] })}
              className="size-4"
            />
            {t(`channels.${c}`)}
            {c === "email" && !options.mail_ready ? (
              <span className="text-xs text-fg-muted">({t("emailNotSetUp")})</span>
            ) : null}
          </label>
        ))}
      </fieldset>
      {post ? (
        <label className={field}>
          {t("postIn")}
          <select
            value={step.destination_id ?? ""}
            onChange={(e) => set({ ...step, destination_id: e.target.value || null })}
            className={control}
          >
            <option value="">{t("choose")}</option>
            {options.destinations
              .filter((d) => d.detail.startsWith(kind))
              .map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} · {d.detail.split(" · ")[1]}
                </option>
              ))}
          </select>
          <span className="text-xs font-normal text-fg-muted">{t("destinationsHint")}</span>
        </label>
      ) : (
        <Recipients
          value={step.to}
          onChange={(to) => set({ ...step, to })}
          email={step.channel === "email"}
        />
      )}
      <label className={field}>
        {t("message")}
        <textarea
          value={step.message}
          onChange={(e) => set({ ...step, message: e.target.value })}
          className={`${area} font-sans text-sm`}
        />
      </label>
      <Fields fields={fields} />
    </div>
  );
}

function ApprovalFields({
  step,
  set,
  options,
  spec,
}: {
  step: Of<"approval">;
  set: (s: Step) => void;
  options: Options;
  spec: Spec;
}) {
  const t = useTranslations("automations");
  const editable = fieldsBefore(spec, step.id)
    .map((f) => f.replace(/[{}]/g, ""))
    .filter((f) => f.startsWith("step"));
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("approvers")}
          <select
            value={step.approver_group_id ?? ""}
            onChange={(e) => set({ ...step, approver_group_id: e.target.value || null })}
            className={control}
          >
            <option value="">{t("platformAdmins")}</option>
            {options.groups.map((g) => (
              <option key={g.id} value={g.id}>
                {t("groupAnyOne", { name: g.name })}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 self-end pb-2 text-sm">
          <input
            type="checkbox"
            checked={step.required === 2}
            onChange={(e) => set({ ...step, required: e.target.checked ? 2 : 1 })}
            className="size-4"
          />
          {t("twoApprovers")}
        </label>
        <label className={field}>
          {t("ifNobody")}
          <input
            type="number"
            min={1}
            max={168}
            value={step.timeout_hours}
            onChange={(e) => set({ ...step, timeout_hours: Number(e.target.value) || 1 })}
            className={control}
          />
          <span className="text-xs font-normal text-fg-muted">{t("hours")}</span>
        </label>
        <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
          <legend className="mb-1 text-[13px] font-medium">{t("thenDo")}</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`timeout-${step.id}`}
              checked={step.on_timeout === "escalate"}
              onChange={() => set({ ...step, on_timeout: "escalate" })}
              className="size-4"
            />
            {t("escalateTo")}
            <select
              aria-label={t("escalateGroup")}
              value={step.escalate_group_id ?? ""}
              onChange={(e) =>
                set({ ...step, on_timeout: "escalate", escalate_group_id: e.target.value || null })
              }
              className={`${control} h-8 w-auto`}
            >
              <option value="">{t("choose")}</option>
              {options.groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`timeout-${step.id}`}
              checked={step.on_timeout === "cancel"}
              onChange={() => set({ ...step, on_timeout: "cancel", escalate_group_id: null })}
              className="size-4"
            />
            {t("cancelRun")}
          </label>
        </fieldset>
      </div>
      <fieldset className="m-0 flex flex-wrap gap-4 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("approverSees")}</legend>
        {(["reasoning", "draft", "tool_call"] as const).map((x) => (
          <label key={x} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={step.shows.includes(x)}
              onChange={(e) =>
                set({
                  ...step,
                  shows: e.target.checked ? [...step.shows, x] : step.shows.filter((y) => y !== x),
                })
              }
              className="size-4"
            />
            {t(`sees.${x}`)}
          </label>
        ))}
      </fieldset>
      <label className={`${field} max-w-[420px]`}>
        {t("editableField")}
        <select
          value={step.editable ?? ""}
          onChange={(e) => set({ ...step, editable: e.target.value || null })}
          className={control}
        >
          <option value="">{t("nothingEditable")}</option>
          {editable.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function StepFields({
  step,
  set,
  options,
  spec,
}: {
  step: Step;
  set: (s: Step) => void;
  options: Options;
  spec: Spec;
}) {
  const fields = fieldsBefore(spec, step.id);
  switch (step.type) {
    case "agent":
      return <AgentFields step={step} set={set} options={options} fields={fields} />;
    case "condition":
      return <ConditionFields step={step} set={set} spec={spec} fields={fields} />;
    case "approval":
      return <ApprovalFields step={step} set={set} options={options} spec={spec} />;
    case "tool":
      return <ToolFields step={step} set={set} options={options} fields={fields} />;
    default:
      return <NotifyFields step={step} set={set} options={options} fields={fields} />;
  }
}

/** One step, with the step type switch. With
 * `following`, an approval step is edited with the actions after it
 * (AutomationApprovalStep.html). */
export function StepEditor({
  automation,
  options,
  stepId,
  following = false,
  onClose,
}: {
  automation: Automation;
  options: Options;
  stepId: string;
  following?: boolean;
  /** Inside the automation's page: close in place instead of going back to it. */
  onClose?: () => void;
}) {
  const t = useTranslations("automations");
  const router = useRouter();
  const [spec, setSpec] = useState<Spec>(automation.spec);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const index = spec.steps.findIndex((s) => s.id === stepId);
  const step = spec.steps[index];
  if (!step) return <p className="m-0 text-sm text-red">{t("stepGone")}</p>;
  // In place, an approval is edited with the actions after it, like on its own page.
  const withFollowing = following || (!!onClose && step.type === "approval");
  const close = () => {
    if (onClose) {
      onClose();
      router.refresh();
    } else router.push(`/admin/automations/${automation.id}`);
  };
  const setStep = (next: Step) =>
    setSpec({ ...spec, steps: spec.steps.map((s) => (s.id === next.id ? next : s)) });
  const after: Step[] = [];
  if (withFollowing) {
    for (const s of spec.steps.slice(index + 1)) {
      if (s.type !== "tool" && s.type !== "notify") break;
      after.push(s);
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await saveSpec(automation, spec, { note: t("stepChanged", { id: stepId }) });
      close();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  function changeType(type: StepType) {
    const next = newStep(type, step!.id, automation.chatbot_id);
    if (type === "approval" && !following && !onClose) {
      // Approvals are edited on their own page, with the actions after them.
      void saveSpec(automation, {
        ...spec,
        steps: spec.steps.map((s) => (s.id === next.id ? next : s)),
      })
        .then((saved) => router.push(stepHref(saved.id, next)))
        .catch((e: unknown) => setError(errorText(e)));
      return;
    }
    setStep({ ...next, name: step!.name });
  }

  return (
    <div className="flex flex-col gap-5">
      {!withFollowing || onClose ? (
        <fieldset className="m-0 flex flex-wrap gap-2 border-0 p-0">
          <legend className="mb-1 text-[13px] font-medium">{t("stepType")}</legend>
          {(["agent", "condition", "approval", "tool", "notify"] as const).map((type) => (
            <label
              key={type}
              className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm ${step.type === type ? "border-accent" : "border-line"}`}
            >
              <input
                type="radio"
                name="step_type"
                checked={step.type === type}
                onChange={() => changeType(type)}
                className="size-4"
              />
              {t(`stepTypes.${type}`)}
            </label>
          ))}
        </fieldset>
      ) : null}
      {[step, ...after].map((s) => (
        <section
          key={s.id}
          aria-labelledby={`h-${s.id}`}
          className={
            onClose
              ? "flex flex-col gap-4"
              : "flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
          }
        >
          <h2
            id={`h-${s.id}`}
            // In place, the step's card already names the step being edited.
            className={onClose && s.id === step.id ? "sr-only" : "m-0 text-base font-semibold"}
          >
            {spec.steps.findIndex((x) => x.id === s.id) + 1} · {t(`stepTypes.${s.type}`)}
          </h2>
          <label className={field}>
            {t("stepName")}
            <input
              value={s.name}
              onChange={(e) => setStep({ ...s, name: e.target.value })}
              className={control}
            />
          </label>
          <StepFields step={s} set={setStep} options={options} spec={spec} />
          {s.type === "tool" ? (
            <p className="m-0 text-xs text-fg-muted">
              {t("toolRunsAs", { name: automation.runs_as?.name ?? "—" })}
            </p>
          ) : null}
        </section>
      ))}
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button onClick={onClose ?? (() => router.push(`/admin/automations/${automation.id}`))}>
          {t("cancel")}
        </Button>
        <Button variant="primary" disabled={busy} onClick={save}>
          {withFollowing && after.length ? t("saveSteps") : t("saveStep")}
        </Button>
        {step.type === "agent" ? (
          <RunNow id={automation.id} label={t("testSampleEvent")} dryOnly />
        ) : null}
      </div>
    </div>
  );
}
