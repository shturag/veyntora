"use client";

import { Badge, Button, Dialog } from "@veyntora/ui";
import {
  ArrowDown,
  ArrowUp,
  Bot,
  CircleAlert,
  GitBranch,
  Plus,
  Send,
  ShieldCheck,
  Trash2,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/chat";
import { sameText } from "@/lib/dates";

import { DeleteAutomation, PauseResume, RunNow } from "./list-actions";
import { StepEditor } from "./step-editor";
import { TriggerEditor } from "./trigger-editor";
import {
  control,
  errorText,
  field,
  newStep,
  nextStepId,
  RUN_TONE,
  saveSpec,
  STATUS_TONE,
  type Automation,
  type Options,
  type Spec,
  type Step,
  type StepType,
} from "./spec";

const TYPES: StepType[] = ["agent", "condition", "approval", "tool", "notify"];

const ICONS: Record<StepType, LucideIcon> = {
  agent: Bot,
  condition: GitBranch,
  approval: ShieldCheck,
  tool: Wrench,
  notify: Send,
};

// Steps on a line: each card hangs off a connector to the next one.
const stepRow =
  "relative flex flex-wrap items-start gap-3 rounded-lg border border-line bg-surface p-4 [&+&]:mt-3 [&+&]:before:absolute [&+&]:before:-top-3 [&+&]:before:left-[35px] [&+&]:before:h-3 [&+&]:before:w-px [&+&]:before:bg-line-strong";
// The editor opens inside the card, under the step's summary (flex-wrap puts it on its own row).
const inlineEditor = "basis-full border-t border-line pt-4 mt-1";
const stepIcon = (tone: "accent" | "amber" | "neutral") =>
  `flex size-9 shrink-0 items-center justify-center rounded-lg ${
    tone === "accent"
      ? "bg-accent-soft text-accent"
      : tone === "amber"
        ? "bg-amber-soft text-amber"
        : "bg-sunken text-fg-secondary"
  }`;

type Problem = {
  text: string;
  /** The step it is about (numbered from 1), if any. */
  step: number | null;
  /** What to open on this page: "trigger" or a step id. */
  open: string | null;
  /** Another page that fixes it (a chatbot's Access page). */
  href: string | null;
};

/** The API's problems with where each is fixed: "Step 2: …" (numbered from 1, without the
 *  trigger), "Trigger: …", or a chatbot's Access page. */
function located(problems: string[], automation: Automation, options: Options): Problem[] {
  return problems.map((text) => {
    const step = /^Step (\d+):/.exec(text);
    if (step) {
      const n = Number(step[1]);
      return { text, step: n, open: automation.spec.steps[n - 1]?.id ?? null, href: null };
    }
    if (text.startsWith("Trigger:")) return { text, step: null, open: "trigger", href: null };
    const bot = options.chatbots.find(
      (b) => text.includes(` ${b.name} `) || text.includes(` ${b.name}:`),
    );
    if (bot && text.includes("Access page")) {
      return { text, step: null, open: null, href: `/admin/chatbots/${bot.id}/access` };
    }
    return { text, step: null, open: null, href: null };
  });
}

function stepLine(step: Step, options: Options, t: ReturnType<typeof useTranslations>): string {
  const name = (id: string | null | undefined, list: { id: string; name: string }[]) =>
    list.find((o) => o.id === id)?.name ?? "—";
  switch (step.type) {
    case "agent":
      return `${name(step.chatbot_id, options.chatbots)} · ${t("toolsCount", { count: step.tool_ids.length })}`;
    case "condition":
      return step.rules
        .map((r) => `${r.field} ${t(`ops.${r.op}`)} ${r.value}`)
        .join(` ${step.join} `);
    case "approval":
      return `${step.approver_group_id ? name(step.approver_group_id, options.groups) : t("platformAdmins")}${
        step.required === 2 ? ` · ${t("twoApprovers")}` : ""
      } · ${t("timeoutLine", { hours: step.timeout_hours })}`;
    case "tool":
      return name(step.tool_id, options.tools);
    default:
      return `${t(`channels.${step.channel}`)}${
        step.destination_id ? ` · ${name(step.destination_id, options.destinations)}` : ""
      }`;
  }
}

/** The builder: trigger, steps, safety, runs, versions. */
export function Builder({
  automation,
  options,
  editor,
}: {
  automation: Automation;
  options: Options;
  editor: boolean;
}) {
  const t = useTranslations("automations");
  const format = useFormatter();
  const router = useRouter();
  const [spec, setSpec] = useState<Spec>(automation.spec);
  // A version saved in place (a step, the trigger) replaces the steps shown here.
  const [shown, setShown] = useState(automation.version);
  if (automation.version !== shown) {
    setShown(automation.version);
    setSpec(automation.spec);
  }
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<{ token: string; url: string } | null>(null);
  const [adding, setAdding] = useState(false);
  // The trigger or the step being edited in place ("trigger" or a step id).
  const [editing, setEditing] = useState<string | null>(null);
  // Just saved (a new step): the editor needs it before the page has reloaded.
  const [fresh, setFresh] = useState<Automation | null>(null);
  const current = fresh ?? automation;
  const closeEditor = () => {
    setEditing(null);
    setFresh(null);
  };
  const dirty = JSON.stringify(spec) !== JSON.stringify(automation.spec);
  const problems = located(automation.problems, automation, options);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ ok: true, text: done });
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
    } finally {
      setBusy(false);
    }
  }

  const save = (next: Spec, done: string) =>
    run(async () => {
      const saved = await saveSpec(automation, next);
      setSpec(saved.spec);
      return saved;
    }, done);

  function move(i: number, by: -1 | 1) {
    const steps = [...spec.steps];
    const [s] = steps.splice(i, 1);
    steps.splice(i + by, 0, s!);
    setSpec({ ...spec, steps });
  }

  async function add(type: StepType) {
    const step = newStep(type, nextStepId(spec), automation.chatbot_id);
    setAdding(false);
    setBusy(true);
    try {
      const saved = await saveSpec(
        automation,
        { ...spec, steps: [...spec.steps, step] },
        { note: t("addedStep") },
      );
      setSpec(saved.spec);
      setFresh(saved);
      setEditing(step.id);
      setBusy(false);
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
      setBusy(false);
    }
  }

  const safety = spec.safety;
  const setSafety = (patch: Partial<Spec["safety"]>) =>
    setSpec({ ...spec, safety: { ...safety, ...patch } });

  return (
    <div className="grid grid-cols-[1fr_320px] gap-5 max-[1000px]:grid-cols-1">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h1 className="m-0 text-2xl font-bold">{automation.name}</h1>
            <Badge tone={STATUS_TONE[automation.status]}>
              {t(`statuses.${automation.status}`)}
            </Badge>
            <span className="text-xs text-fg-muted">
              {t("versionN", { n: automation.version })}
            </span>
          </div>
          {editor ? (
            <div className="flex flex-wrap items-center gap-2">
              <RunNow id={automation.id} label={t("testSample")} dryOnly />
              <Button
                variant={dirty ? "primary" : "secondary"}
                disabled={busy || !dirty}
                onClick={() => save(spec, t("savedVersion", { n: automation.version + 1 }))}
              >
                {t("saveChanges")}
              </Button>
              {automation.status === "draft" ? (
                <Button
                  // Saving comes first while there are changes; then activating.
                  variant={dirty ? "secondary" : "primary"}
                  disabled={busy || dirty || automation.problems.length > 0}
                  title={
                    dirty ? t("saveFirst") : automation.problems.length ? t("fixFirst") : undefined
                  }
                  onClick={() =>
                    run(
                      () =>
                        api(`/v1/admin/automations/${automation.id}/activate`, {
                          method: "POST",
                          body: "{}",
                        }),
                      t("activated"),
                    )
                  }
                >
                  {t("activate")}
                </Button>
              ) : (
                <PauseResume id={automation.id} status={automation.status} />
              )}
              <span aria-hidden className="mx-1 h-6 w-px bg-line" />
              <DeleteAutomation
                id={automation.id}
                name={automation.name}
                status={automation.status}
                then="/admin/automations"
              />
            </div>
          ) : null}
        </div>
        {automation.description ? (
          <p className="m-0 text-sm text-fg-secondary">{automation.description}</p>
        ) : null}
        {message ? (
          <p
            role={message.ok ? "status" : "alert"}
            className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
          >
            {message.text}
          </p>
        ) : null}
        {problems.length ? (
          <section
            aria-labelledby="problems"
            className="flex flex-col gap-2 rounded-lg border border-amber/40 bg-amber-soft/40 p-4"
          >
            <h2
              id="problems"
              className="m-0 flex items-center gap-2 text-sm font-semibold text-amber"
            >
              <CircleAlert aria-hidden className="size-4" />
              {t("problemsTitle")}
              <span className="font-normal text-fg-muted">
                {t("toFix", { count: problems.length })}
              </span>
            </h2>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
              {problems.map((p) => (
                <li key={p.text} className="flex items-baseline gap-2">
                  <span
                    aria-hidden
                    className="size-1.5 shrink-0 translate-y-[-2px] rounded-full bg-amber"
                  />
                  {p.open && editor ? (
                    <button
                      type="button"
                      disabled={dirty}
                      onClick={() => setEditing(p.open)}
                      className="text-left text-fg hover:underline disabled:no-underline"
                    >
                      {p.text}
                    </button>
                  ) : p.href && editor ? (
                    <Link href={p.href} className="text-fg no-underline hover:underline">
                      {p.text}
                    </Link>
                  ) : (
                    <span>{p.text}</span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <ol className="m-0 flex list-none flex-col p-0" aria-label={t("stepsLabel")}>
          <li className={stepRow}>
            <span aria-hidden className={stepIcon("accent")}>
              <Zap className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium text-fg-muted uppercase">{t("when")}</div>
              <div className="text-sm font-semibold">{t(`triggerTypes.${spec.trigger.type}`)}</div>
              <div className="text-xs text-fg-muted">
                {automation.next_runs.length
                  ? t("nextRuns", {
                      runs: automation.next_runs
                        .map((r) =>
                          sameText(
                            format.dateTime(new Date(r), {
                              weekday: "short",
                              day: "numeric",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            }),
                          ),
                        )
                        .join(" · "),
                    })
                  : spec.trigger.type === "event"
                    ? spec.trigger.event
                    : ""}
              </div>
            </div>
            {editor && editing !== "trigger" ? (
              <Button
                size="sm"
                disabled={dirty || editing !== null}
                title={dirty ? t("saveFirst") : undefined}
                onClick={() => setEditing("trigger")}
              >
                {t("edit")}
              </Button>
            ) : null}
            {editing === "trigger" ? (
              <div className={inlineEditor}>
                <TriggerEditor automation={current} options={options} onClose={closeEditor} />
              </div>
            ) : null}
          </li>
          {spec.steps.map((step, i) => {
            const Icon = ICONS[step.type];
            const flagged = problems.some((p) => p.step === i + 1);
            return (
              <li key={step.id} className={stepRow}>
                <span aria-hidden className={stepIcon(flagged ? "amber" : "neutral")}>
                  <Icon className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-fg-muted uppercase">
                    {t("stepN", { n: i + 1 })} · {t(`stepTypes.${step.type}`)}
                  </div>
                  <div className="text-sm font-semibold">
                    {step.name || t(`stepTypes.${step.type}`)}
                  </div>
                  <div className="truncate text-xs text-fg-muted">{stepLine(step, options, t)}</div>
                  {flagged ? (
                    <div className="mt-1 flex items-center gap-1 text-xs font-medium text-amber">
                      <CircleAlert aria-hidden className="size-3.5" />
                      {t("needsAttention")}
                    </div>
                  ) : null}
                </div>
                {editor && editing !== step.id ? (
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("moveUp", { n: i + 1 })}
                      title={t("moveUp", { n: i + 1 })}
                      disabled={i === 0}
                      onClick={() => move(i, -1)}
                    >
                      <ArrowUp aria-hidden className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("moveDown", { n: i + 1 })}
                      title={t("moveDown", { n: i + 1 })}
                      disabled={i === spec.steps.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      <ArrowDown aria-hidden className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t("removeStep", { n: i + 1 })}
                      title={t("removeStep", { n: i + 1 })}
                      onClick={() =>
                        setSpec({ ...spec, steps: spec.steps.filter((s) => s.id !== step.id) })
                      }
                    >
                      <Trash2 aria-hidden className="size-4" />
                    </Button>
                    <Button
                      size="sm"
                      className="ml-1"
                      disabled={dirty || editing !== null}
                      title={dirty ? t("saveFirst") : undefined}
                      onClick={() => setEditing(step.id)}
                    >
                      {t("edit")}
                    </Button>
                  </div>
                ) : null}
                {editing === step.id ? (
                  <div className={inlineEditor}>
                    <StepEditor
                      automation={current}
                      options={options}
                      stepId={step.id}
                      onClose={closeEditor}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
          {editor ? (
            <li className="relative mt-3">
              <span aria-hidden className="absolute -top-3 left-[35px] h-3 w-px bg-line-strong" />
              <button
                type="button"
                disabled={busy || dirty || editing !== null}
                title={dirty ? t("saveFirst") : undefined}
                onClick={() => setAdding(true)}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3 text-sm font-medium text-fg-secondary hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Plus aria-hidden className="size-4" />
                {t("addStep").replace(/^\+\s*/, "")}
              </button>
            </li>
          ) : null}
        </ol>
        {editor ? (
          <Dialog
            open={adding}
            onOpenChange={setAdding}
            title={t("addStepTitle")}
            closeLabel={t("close")}
          >
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {TYPES.map((type) => {
                const Icon = ICONS[type];
                return (
                  <li key={type}>
                    <button
                      type="button"
                      onClick={() => add(type)}
                      className="flex w-full items-start gap-3 rounded-md border border-line p-3 text-left hover:border-accent"
                    >
                      <span aria-hidden className={stepIcon("neutral")}>
                        <Icon className="size-4" />
                      </span>
                      <span className="flex flex-col">
                        <span className="text-sm font-semibold">{t(`stepTypes.${type}`)}</span>
                        <span className="text-xs text-fg-muted">{t(`stepHints.${type}`)}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Dialog>
        ) : null}
        {spec.trigger.type === "event" && editor ? (
          <section
            aria-labelledby="hook"
            className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
          >
            <h2 id="hook" className="m-0 text-sm font-semibold">
              {t("hookTitle")}
            </h2>
            <p className="m-0 text-xs text-fg-muted">{t("hookText")}</p>
            {token ? (
              <div className="flex flex-col gap-1 text-xs">
                <span>{t("hookUrl")}</span>
                <code className="rounded bg-sunken p-2 break-all">{token.url}</code>
                <span>{t("hookToken")}</span>
                <code className="rounded bg-sunken p-2 break-all">{token.token}</code>
                <span className="text-amber">{t("hookOnce")}</span>
              </div>
            ) : (
              <span className="text-xs text-fg-muted">
                {automation.hook_prefix
                  ? t("hookCurrent", { prefix: automation.hook_prefix })
                  : t("hookNone")}
              </span>
            )}
            <div>
              <Button
                size="sm"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    setToken(
                      await api<{ token: string; url: string }>(
                        `/v1/admin/automations/${automation.id}/hook-token`,
                        {
                          method: "POST",
                          body: "{}",
                        },
                      ),
                    );
                  }, t("hookCreated"))
                }
              >
                {automation.hook_prefix ? t("hookReplace") : t("hookCreate")}
              </Button>
            </div>
          </section>
        ) : null}
      </div>
      <aside className="flex flex-col gap-4">
        <section
          aria-labelledby="safety"
          className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        >
          <h2 id="safety" className="m-0 text-sm font-semibold">
            {t("safety")}
          </h2>
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0" disabled={!editor}>
            <legend className="mb-1 text-[13px] font-medium">{t("autonomyLabel")}</legend>
            {(["approve", "suggest", "report"] as const).map((a) => (
              <label key={a} className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="autonomy"
                  checked={safety.autonomy === a}
                  onChange={() => setSafety({ autonomy: a })}
                  className="mt-0.5 size-4"
                />
                <span>
                  {t(`autonomy.${a}`)}
                  <span className="block text-xs text-fg-muted">{t(`autonomyHints.${a}`)}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className={field}>
            {t("runsAs")}
            {automation.runs_as ? (
              <Link
                href={`/admin/users/${automation.runs_as.id}`}
                className="text-sm font-normal underline"
              >
                {automation.runs_as.name}
              </Link>
            ) : (
              <span className="text-sm font-normal">—</span>
            )}
            <span className="text-xs font-normal text-fg-muted">{t("runsAsHint")}</span>
          </div>
          <label className={field}>
            {t("maxCost")}
            <input
              type="number"
              min={0}
              step="0.01"
              disabled={!editor}
              value={safety.max_cost_per_run ?? ""}
              onChange={(e) =>
                setSafety({ max_cost_per_run: e.target.value === "" ? null : e.target.value })
              }
              className={control}
            />
          </label>
          <label className={field}>
            {t("maxRuns")}
            <input
              type="number"
              min={1}
              max={1000}
              disabled={!editor}
              value={safety.max_runs_per_hour}
              onChange={(e) => setSafety({ max_runs_per_hour: Number(e.target.value) || 1 })}
              className={control}
            />
          </label>
          <label className={field}>
            {t("onFailure")}
            <select
              disabled={!editor}
              value={safety.retries}
              onChange={(e) => setSafety({ retries: Number(e.target.value) })}
              className={control}
            >
              {[0, 1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  {t("retries", { count: n })}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              disabled={!editor}
              checked={safety.alert_owner_on_failure}
              onChange={(e) => setSafety({ alert_owner_on_failure: e.target.checked })}
              className="size-4"
            />
            {t("alertOwner")}
          </label>
        </section>
        <section
          aria-labelledby="recent"
          className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
        >
          <h2 id="recent" className="m-0 text-sm font-semibold">
            {t("recentRuns")}
          </h2>
          {automation.recent_runs.length === 0 ? (
            <p className="m-0 text-xs text-fg-muted">{t("noRuns")}</p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
              {automation.recent_runs.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2">
                  <Link href={`/admin/runs/${r.id}`} className="min-w-0 truncate underline">
                    {r.summary}
                    {r.dry_run ? ` · ${t("dry")}` : ""}
                  </Link>
                  <Badge tone={RUN_TONE[r.status]}>
                    {t(`runStatuses.${r.status}`)}
                    {r.seconds != null ? ` · ${format.number(r.seconds)} s` : ""}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section
          aria-labelledby="versions"
          className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
        >
          <h2 id="versions" className="m-0 text-sm font-semibold">
            {t("versions")}
          </h2>
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
            {automation.versions.map((v) => (
              <li key={v.number} className="flex items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="font-medium">v{v.number}</span>
                  <span className="text-xs text-fg-muted">
                    {" "}
                    ·{" "}
                    {sameText(
                      format.dateTime(new Date(v.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }),
                    )}
                    {v.change_note ? ` · ${v.change_note}` : ""}
                  </span>
                </span>
                {editor && v.number !== automation.version ? (
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () =>
                          api(`/v1/admin/automations/${automation.id}/restore`, {
                            method: "POST",
                            body: JSON.stringify({ number: v.number }),
                          }),
                        t("restored", { n: v.number }),
                      )
                    }
                  >
                    {t("restore")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  );
}
