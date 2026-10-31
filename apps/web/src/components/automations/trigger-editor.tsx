"use client";

import { Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/chat";

import { RulesEditor } from "./rules-editor";
import {
  area,
  control,
  errorText,
  field,
  linesOf,
  objectOf,
  saveSpec,
  type Automation,
  type Options,
  type Trigger,
} from "./spec";

type Kind = Trigger["type"];
type Schedule = Extract<Trigger, { type: "schedule" }>;
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const ZONES = [
  "Europe/Berlin",
  "Europe/Vienna",
  "Europe/Zurich",
  "Europe/London",
  "Europe/Paris",
  "UTC",
  "America/New_York",
];
const DE_STATES = [
  "BW",
  "BY",
  "BE",
  "BB",
  "HB",
  "HH",
  "HE",
  "MV",
  "NI",
  "NW",
  "RP",
  "SL",
  "SN",
  "ST",
  "SH",
  "TH",
];

const DEFAULTS: Record<Kind, Trigger> = {
  schedule: {
    type: "schedule",
    repeat: "weekly",
    time: "07:45",
    days: ["mon"],
    day_of_month: 1,
    every_hours: 4,
    cron: null,
    timezone: "Europe/Berlin",
    skip_holidays: null,
  },
  event: {
    type: "event",
    app: "Custom webhook",
    event: "ticket.created",
    conditions: [],
    dedupe_field: null,
    dedupe_minutes: 0,
    active_hours: "always",
    timezone: "Europe/Berlin",
  },
  file: {
    type: "file",
    source_id: null,
    folder: "",
    file_types: [],
    when: "added",
    wait_for_index: true,
  },
  watcher: {
    type: "watcher",
    tool_id: null,
    arguments: {},
    every: "day",
    time: "06:00",
    timezone: "Europe/Berlin",
    fire_when: [{ field: "event.end_date", op: "within_days", value: "60" }],
    once_per: "id",
  },
};

/** The trigger (prototype: AutomationTrigger.html): schedule, event, new file or watcher. */
export function TriggerEditor({
  automation,
  options,
}: {
  automation: Automation;
  options: Options;
}) {
  const t = useTranslations("automations");
  const format = useFormatter();
  const router = useRouter();
  const [trigger, setTrigger] = useState<Trigger>(automation.spec.trigger);
  const [nextRuns, setNextRuns] = useState<string[] | null>(null);
  const [sample, setSample] = useState("");
  const [check, setCheck] = useState<{ ok: boolean; text: string } | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Trigger>) => setTrigger({ ...trigger, ...patch } as Trigger);

  useEffect(() => {
    if (trigger.type !== "schedule" && trigger.type !== "watcher") return;
    const timer = setTimeout(() => {
      api<{ next_runs: string[] }>("/v1/admin/automations/schedule-preview", {
        method: "POST",
        body: JSON.stringify({ trigger }),
      })
        .then((r) => setNextRuns(r.next_runs))
        .catch(() => setNextRuns([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [trigger]);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await saveSpec(automation, { ...automation.spec, trigger }, { note: t("triggerChanged") });
      router.push(`/admin/automations/${automation.id}`);
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: t("failed", { reason: errorText(e) }) });
      setBusy(false);
    }
  }

  async function test() {
    if (trigger.type !== "event" && trigger.type !== "watcher") return;
    let event: unknown;
    try {
      event = JSON.parse(sample || "{}");
    } catch {
      setCheck({ ok: false, text: t("inputNotJson") });
      return;
    }
    const rules = trigger.type === "event" ? trigger.conditions : trigger.fire_when;
    try {
      const r = await api<{ matches: boolean }>("/v1/admin/automations/condition-test", {
        method: "POST",
        body: JSON.stringify({ rules, event }),
      });
      setCheck({ ok: r.matches, text: r.matches ? t("matches") : t("noMatch") });
    } catch (e) {
      setCheck({ ok: false, text: t("failed", { reason: errorText(e) }) });
    }
  }

  const when = (iso: string) =>
    format.dateTime(new Date(iso), {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  const eventFields = [
    "{event.key}",
    "{event.project}",
    "{event.channel}",
    "{event.amount}",
    "{event.end_date}",
  ];

  return (
    <div className="flex flex-col gap-5">
      <fieldset className="m-0 grid grid-cols-4 gap-2 border-0 p-0 max-[800px]:grid-cols-2">
        <legend className="mb-2 text-[13px] font-medium">{t("triggerType")}</legend>
        {(["schedule", "event", "file", "watcher"] as const).map((k) => (
          <label
            key={k}
            className={`flex cursor-pointer flex-col gap-0.5 rounded-md border p-3 ${trigger.type === k ? "border-accent" : "border-line"}`}
          >
            <span className="flex items-center gap-2 text-sm font-semibold">
              <input
                type="radio"
                name="trigger_type"
                checked={trigger.type === k}
                onChange={() =>
                  setTrigger(
                    k === automation.spec.trigger.type ? automation.spec.trigger : DEFAULTS[k],
                  )
                }
                className="size-4"
              />
              {t(`triggerTypes.${k}`)}
            </span>
            <span className="text-xs text-fg-muted">{t(`triggerHints.${k}`)}</span>
          </label>
        ))}
      </fieldset>

      {trigger.type === "schedule" ? <ScheduleFields trigger={trigger} set={set} /> : null}

      {trigger.type === "file" ? (
        <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
          <label className={field}>
            {t("dataSource")}
            <select
              value={trigger.source_id ?? ""}
              onChange={(e) => set({ source_id: e.target.value || null })}
              className={control}
            >
              <option value="">{t("choose")}</option>
              {options.sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.detail})
                </option>
              ))}
            </select>
          </label>
          <label className={field}>
            {t("folder")}
            <input
              value={trigger.folder}
              onChange={(e) => set({ folder: e.target.value })}
              placeholder="contracts/new"
              className={control}
            />
          </label>
          <label className={field}>
            {t("fileTypes")}
            <input
              value={trigger.file_types.join(", ")}
              onChange={(e) =>
                set({
                  file_types: e.target.value
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                })
              }
              placeholder="pdf, docx"
              className={control}
            />
          </label>
          <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium">{t("fileWhen")}</legend>
            {(["added", "added_or_changed"] as const).map((w) => (
              <label key={w} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="when"
                  checked={trigger.when === w}
                  onChange={() => set({ when: w })}
                  className="size-4"
                />
                {t(`fileWhens.${w}`)}
              </label>
            ))}
          </fieldset>
          <fieldset className="m-0 flex flex-col gap-1 border-0 p-0">
            <legend className="mb-1 text-[13px] font-medium">{t("waitForIndex")}</legend>
            {[true, false].map((v) => (
              <label key={String(v)} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="wait"
                  checked={trigger.wait_for_index === v}
                  onChange={() => set({ wait_for_index: v })}
                  className="size-4"
                />
                {v ? t("waitYes") : t("waitNo")}
              </label>
            ))}
          </fieldset>
        </div>
      ) : null}

      {trigger.type === "watcher" ? (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-4 max-[800px]:grid-cols-1">
            <label className={field}>
              {t("checkUsing")}
              <select
                value={trigger.tool_id ?? ""}
                onChange={(e) => set({ tool_id: e.target.value || null })}
                className={control}
              >
                <option value="">{t("choose")}</option>
                {options.tools
                  .filter((x) => x.access === "read")
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.detail}: {x.name}
                    </option>
                  ))}
              </select>
              <span className="text-xs font-normal text-fg-muted">{t("readToolsOnly")}</span>
            </label>
            <label className={field}>
              {t("checkEvery")}
              <select
                value={trigger.every}
                onChange={(e) => set({ every: e.target.value as "hour" | "day" })}
                className={control}
              >
                <option value="day">{t("everyDay")}</option>
                <option value="hour">{t("everyHour")}</option>
              </select>
            </label>
            <label className={field}>
              {t("time")}
              <input
                type="time"
                value={trigger.time}
                onChange={(e) => set({ time: e.target.value })}
                className={control}
              />
            </label>
          </div>
          <label className={field}>
            {t("toolArguments")}
            <textarea
              defaultValue={linesOf(trigger.arguments)}
              onChange={(e) => set({ arguments: objectOf(e.target.value) })}
              placeholder="status=active"
              className={area}
            />
            <span className="text-xs font-normal text-fg-muted">{t("argumentsHint")}</span>
          </label>
          <RulesEditor
            label={t("fireWhen")}
            rules={trigger.fire_when}
            onChange={(fire_when) => set({ fire_when })}
            fields={eventFields}
            min={1}
          />
          <label className={`${field} max-w-[320px]`}>
            {t("oncePer")}
            <input
              value={trigger.once_per ?? ""}
              onChange={(e) => set({ once_per: e.target.value || null })}
              placeholder="id"
              className={`${control} font-mono`}
            />
            <span className="text-xs font-normal text-fg-muted">{t("oncePerHint")}</span>
          </label>
        </div>
      ) : null}

      {trigger.type === "event" ? (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
            <label className={field}>
              {t("app")}
              <input
                value={trigger.app}
                onChange={(e) => set({ app: e.target.value })}
                className={control}
              />
            </label>
            <label className={field}>
              {t("eventName")}
              <input
                value={trigger.event}
                onChange={(e) => set({ event: e.target.value })}
                className={`${control} font-mono`}
              />
            </label>
          </div>
          <RulesEditor
            label={t("onlyWhen")}
            rules={trigger.conditions}
            onChange={(conditions) => set({ conditions })}
            fields={eventFields}
          />
          <div className="grid grid-cols-3 gap-4 max-[800px]:grid-cols-1">
            <label className={field}>
              {t("dedupeField")}
              <input
                value={trigger.dedupe_field ?? ""}
                onChange={(e) => set({ dedupe_field: e.target.value || null })}
                placeholder="event.key"
                className={`${control} font-mono`}
              />
            </label>
            <label className={field}>
              {t("dedupeMinutes")}
              <input
                type="number"
                min={0}
                value={trigger.dedupe_minutes}
                onChange={(e) => set({ dedupe_minutes: Number(e.target.value) || 0 })}
                className={control}
              />
            </label>
            <label className={field}>
              {t("activeHours")}
              <select
                value={trigger.active_hours}
                onChange={(e) => set({ active_hours: e.target.value as "always" | "working" })}
                className={control}
              >
                <option value="always">{t("always")}</option>
                <option value="working">{t("workingHours")}</option>
              </select>
            </label>
          </div>
        </div>
      ) : null}

      {trigger.type === "event" || trigger.type === "watcher" ? (
        <section
          aria-labelledby="sample"
          className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
        >
          <h2 id="sample" className="m-0 text-sm font-semibold">
            {t("sampleInput")}
          </h2>
          <textarea
            aria-labelledby="sample"
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            placeholder='{"key": "SUP-4821", "project": "SUP", "amount": 640}'
            className={area}
          />
          <div className="flex items-center gap-3">
            <Button size="sm" onClick={test}>
              {t("checkSample")}
            </Button>
            {check ? (
              <span role="status" className={`text-sm ${check.ok ? "text-green" : "text-red"}`}>
                {check.ok ? "✓ " : ""}
                {check.text}
              </span>
            ) : null}
          </div>
          <p className="m-0 text-xs text-fg-muted">{t("sampleHint")}</p>
        </section>
      ) : null}

      {trigger.type === "schedule" || trigger.type === "watcher" ? (
        <p className="m-0 text-sm text-fg-secondary" aria-live="polite">
          {nextRuns === null
            ? ""
            : nextRuns.length
              ? t("nextRuns", { runs: nextRuns.map(when).join(" · ") })
              : t("noNextRuns")}
        </p>
      ) : null}

      {message ? (
        <p role="alert" className="m-0 text-sm text-red">
          {message.text}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button onClick={() => router.push(`/admin/automations/${automation.id}`)}>
          {t("cancel")}
        </Button>
        <Button variant="primary" disabled={busy} onClick={save}>
          {t("saveStep")}
        </Button>
      </div>
    </div>
  );
}

function ScheduleFields({
  trigger,
  set,
}: {
  trigger: Schedule;
  set: (patch: Partial<Schedule>) => void;
}) {
  const t = useTranslations("automations");
  const holidays = trigger.skip_holidays;
  return (
    <div className="flex flex-col gap-4">
      <fieldset className="m-0 flex flex-wrap gap-3 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("repeat")}</legend>
        {(["weekly", "daily", "monthly", "hours", "cron"] as const).map((r) => (
          <label key={r} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="repeat"
              checked={trigger.repeat === r}
              onChange={() => set({ repeat: r })}
              className="size-4"
            />
            {t(`repeats.${r}`)}
          </label>
        ))}
      </fieldset>
      <div className="grid grid-cols-3 gap-4 max-[800px]:grid-cols-1">
        {trigger.repeat === "hours" ? (
          <label className={field}>
            {t("everyNHours")}
            <input
              type="number"
              min={1}
              max={24}
              value={trigger.every_hours}
              onChange={(e) => set({ every_hours: Number(e.target.value) || 1 })}
              className={control}
            />
          </label>
        ) : trigger.repeat === "cron" ? (
          <label className={field}>
            {t("cron")}
            <input
              value={trigger.cron ?? ""}
              onChange={(e) => set({ cron: e.target.value })}
              placeholder="45 7 * * 1"
              className={`${control} font-mono`}
            />
          </label>
        ) : (
          <label className={field}>
            {t("time")}
            <input
              type="time"
              value={trigger.time}
              onChange={(e) => set({ time: e.target.value })}
              className={control}
            />
          </label>
        )}
        {trigger.repeat === "monthly" ? (
          <label className={field}>
            {t("dayOfMonth")}
            <input
              type="number"
              min={1}
              max={28}
              value={trigger.day_of_month}
              onChange={(e) => set({ day_of_month: Number(e.target.value) || 1 })}
              className={control}
            />
          </label>
        ) : null}
        <label className={field}>
          {t("timezone")}
          <select
            value={trigger.timezone}
            onChange={(e) => set({ timezone: e.target.value })}
            className={control}
          >
            {[...new Set([trigger.timezone, ...ZONES])].map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
      </div>
      {trigger.repeat === "weekly" ? (
        <fieldset className="m-0 flex flex-wrap gap-3 border-0 p-0">
          <legend className="mb-1 text-[13px] font-medium">{t("days")}</legend>
          {DAYS.map((d) => (
            <label key={d} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={trigger.days.includes(d)}
                onChange={(e) =>
                  set({
                    days: e.target.checked
                      ? DAYS.filter((x) => x === d || trigger.days.includes(x))
                      : trigger.days.filter((x) => x !== d),
                  })
                }
                className="size-4"
              />
              {t(`weekdays.${d}`)}
            </label>
          ))}
        </fieldset>
      ) : null}
      <fieldset className="m-0 flex flex-wrap items-end gap-3 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("skipHolidays")}</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="holidays"
            checked={holidays !== null}
            onChange={() => set({ skip_holidays: { country: "DE", subdivision: "BW" } })}
            className="size-4"
          />
          {t("yes")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="holidays"
            checked={holidays === null}
            onChange={() => set({ skip_holidays: null })}
            className="size-4"
          />
          {t("no")}
        </label>
        {holidays ? (
          <>
            <label className={field}>
              {t("country")}
              <select
                value={holidays.country}
                onChange={(e) =>
                  set({
                    skip_holidays: {
                      country: e.target.value,
                      subdivision: e.target.value === "DE" ? "BW" : null,
                    },
                  })
                }
                className={control}
              >
                {["DE", "AT", "CH"].map((c) => (
                  <option key={c} value={c}>
                    {t(`countries.${c}` as "countries.DE")}
                  </option>
                ))}
              </select>
            </label>
            {holidays.country === "DE" ? (
              <label className={field}>
                {t("state")}
                <select
                  value={holidays.subdivision ?? ""}
                  onChange={(e) =>
                    set({ skip_holidays: { ...holidays, subdivision: e.target.value || null } })
                  }
                  className={control}
                >
                  <option value="">{t("nationwide")}</option>
                  {DE_STATES.map((s) => (
                    <option key={s} value={s}>
                      {t(`states.${s}` as "states.BW")}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </>
        ) : null}
      </fieldset>
    </div>
  );
}
