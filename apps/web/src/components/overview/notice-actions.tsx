"use client";

import { Button } from "@veyntora/ui";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { control, field, FormDialog, Result, useAction } from "../evaluation/evaluation-actions";

type Notice = components["schemas"]["NoticeRow"];
const COMPONENTS = ["chat", "agent", "documents", "teams", "signin"] as const;

/** "Post status message to users": shown on the status page. */
export function PostNotice({
  allowed,
  names,
}: {
  allowed: boolean;
  names: Record<string, string>;
}) {
  const state = useAction("overview");
  const { t } = state;
  return (
    <FormDialog
      label={t("postNotice")}
      title={t("postNotice")}
      submit={t("post")}
      state={state}
      disabled={!allowed}
      onSubmit={(f) =>
        state.run(
          () =>
            api("/v1/admin/notices", {
              method: "POST",
              body: JSON.stringify({
                kind: f.get("kind"),
                title: f.get("title"),
                body: f.get("body") ?? "",
                components: f.getAll("components").map(String),
                hours: Number(f.get("hours")) || null,
              }),
            }),
          t("noticePosted"),
        )
      }
    >
      <label className={field}>
        {t("kind")}
        <select name="kind" defaultValue="info" className={control}>
          {(["info", "maintenance", "incident"] as const).map((k) => (
            <option key={k} value={k}>
              {t(`kindsNotice.${k}`)}
            </option>
          ))}
        </select>
      </label>
      <label className={field}>
        {t("noticeTitle")}
        <input name="title" required maxLength={255} className={control} />
      </label>
      <label className={field}>
        {t("noticeBody")}
        <textarea
          name="body"
          maxLength={4000}
          className="min-h-[80px] w-full rounded-md border border-line-strong bg-surface p-3 text-sm font-normal"
        />
      </label>
      <fieldset className="m-0 flex flex-wrap gap-3 border-0 p-0">
        <legend className="mb-1 text-[13px] font-medium">{t("affects")}</legend>
        {COMPONENTS.map((c) => (
          <label key={c} className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="components" value={c} className="size-4" />
            {names[c] ?? c}
          </label>
        ))}
      </fieldset>
      <label className={field}>
        {t("hours")}
        <input name="hours" type="number" min={1} max={720} className={control} />
        <span className="text-xs font-normal text-fg-muted">{t("hoursHint")}</span>
      </label>
    </FormDialog>
  );
}

export function EndNotice({ notice, allowed }: { notice: Notice; allowed: boolean }) {
  const state = useAction("overview");
  return (
    <span className="flex items-center gap-2">
      <Button
        size="sm"
        variant="ghost"
        disabled={!allowed || state.busy}
        aria-label={state.t("endNotice", { title: notice.title })}
        onClick={() =>
          state.run(
            () => api(`/v1/admin/notices/${notice.id}/end`, { method: "POST" }),
            state.t("noticeEnded"),
          )
        }
      >
        {state.t("end")}
      </Button>
      <Result message={state.message?.ok ? null : state.message} />
    </span>
  );
}
