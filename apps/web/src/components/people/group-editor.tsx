"use client";

import { Button } from "@veyntora/ui";
import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

import { PersonPicker } from "./person-picker";

type Group = components["schemas"]["GroupDetail"];
type Member = { id: string; name: string; expires_at: string | null };
const ROLES = ["user", "approver", "editor", "owner"] as const;

/** Members (manual groups), the group's roles on each chatbot, and the tools it may use. */
export function GroupEditor({ group: g, canEdit }: { group: Group; canEdit: boolean }) {
  const t = useTranslations("people");
  const format = useFormatter();
  const router = useRouter();
  const manual = g.source === "manual";
  const [members, setMembers] = useState<Member[]>(
    g.member_list
      .filter((m) => m.source === "manual")
      .map((m) => ({ id: m.id, name: m.name, expires_at: m.expires_at })),
  );
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, done: string, then?: () => void) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      setMessage({ ok: true, text: done });
      if (then) then();
      else router.refresh();
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  function saveRoles(botId: string, form: HTMLFormElement) {
    const roles = new FormData(form).getAll("roles").map(String);
    void run(
      () =>
        api(`/v1/admin/groups/${g.id}/roles/${botId}`, {
          method: "PUT",
          body: JSON.stringify({ roles }),
        }),
      t("saved"),
    );
  }

  const status = message ? (
    <p
      role={message.ok ? "status" : "alert"}
      className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
    >
      {message.text}
    </p>
  ) : null;

  return (
    <div className="flex flex-col gap-6">
      {status}
      <section aria-labelledby="members-title" className="flex flex-col gap-2">
        <h2 id="members-title" className="m-0 text-base font-semibold">
          {t("membersCount", { count: g.members })}
        </h2>
        {g.source === "keycloak" ? (
          <p className="m-0 text-xs text-fg-muted">{t("keycloakMembers")}</p>
        ) : null}
        {g.source === "rule" ? (
          <p className="m-0 text-xs text-fg-muted">{t("ruleMembers")}</p>
        ) : null}
        {manual && canEdit ? (
          <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
            {members.map((m, i) => (
              <div key={m.id} className="flex flex-wrap items-center gap-3 text-sm">
                <span className="min-w-40 font-medium">{m.name}</span>
                <label className="flex items-center gap-2 text-xs text-fg-muted">
                  {t("until")}
                  <input
                    type="date"
                    value={m.expires_at?.slice(0, 10) ?? ""}
                    onChange={(e) =>
                      setMembers((list) =>
                        list.map((x, j) =>
                          j === i
                            ? {
                                ...x,
                                expires_at: e.target.value ? `${e.target.value}T23:59:59Z` : null,
                              }
                            : x,
                        ),
                      )
                    }
                    className="h-8 rounded-md border border-line-strong bg-surface px-2 text-sm"
                  />
                </label>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setMembers((list) => list.filter((_, j) => j !== i))}
                >
                  {t("remove")}
                </Button>
              </div>
            ))}
            <div className="flex flex-wrap items-end gap-2">
              <PersonPicker
                label={t("addPerson")}
                value={null}
                onChange={(p) =>
                  p &&
                  !members.some((m) => m.id === p.id) &&
                  setMembers((list) => [...list, { ...p, expires_at: null }])
                }
              />
              <Button
                variant="primary"
                disabled={busy}
                onClick={() =>
                  run(
                    () =>
                      api(`/v1/admin/groups/${g.id}/members`, {
                        method: "PUT",
                        body: JSON.stringify({
                          members: members.map((m) => ({
                            user_id: m.id,
                            expires_at: m.expires_at,
                          })),
                        }),
                      }),
                    t("saved"),
                  )
                }
              >
                {t("saveMembers")}
              </Button>
            </div>
          </div>
        ) : (
          <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
            {g.member_list.length === 0 ? (
              <li className="px-4 py-2 text-sm text-fg-muted">{t("noMembers")}</li>
            ) : null}
            {g.member_list.map((m) => (
              <li
                key={`${m.id}-${m.source}`}
                className="flex justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
              >
                <span>
                  {m.name} <span className="text-xs text-fg-muted">{m.email}</span>
                </span>
                <span className="text-xs text-fg-muted">
                  {m.expires_at
                    ? t("endsOn", {
                        date: format.dateTime(new Date(m.expires_at), { dateStyle: "medium" }),
                      })
                    : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="roles-title" className="flex flex-col gap-2">
        <h2 id="roles-title" className="m-0 text-base font-semibold">
          {t("chatbotRoles")}
        </h2>
        <p className="m-0 text-xs text-fg-muted">{t("rolesHint")}</p>
        <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
          {g.roles.map((r) => (
            <li key={r.chatbot_id} className="border-t border-line px-4 py-2 first:border-t-0">
              <form
                aria-label={r.chatbot}
                onSubmit={(e) => {
                  e.preventDefault();
                  saveRoles(r.chatbot_id, e.currentTarget);
                }}
                className="flex flex-wrap items-center gap-3 text-sm"
              >
                <span className="min-w-44 font-medium">{r.chatbot}</span>
                {ROLES.map((role) => (
                  <label key={role} className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      name="roles"
                      value={role}
                      defaultChecked={r.roles.includes(role)}
                      disabled={!canEdit}
                    />
                    {t(`roles.${role}`)}
                  </label>
                ))}
                {canEdit ? (
                  <Button type="submit" size="sm" disabled={busy}>
                    {t("save")}
                  </Button>
                ) : null}
              </form>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="tools-title" className="flex flex-col gap-2">
        <h2 id="tools-title" className="m-0 text-base font-semibold">
          {t("toolsTitle")}
        </h2>
        {g.tools.length === 0 ? (
          <p className="m-0 text-sm text-fg-muted">{t("noTools")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
            {g.tools.map((tool) => (
              <li
                key={tool.tool_id}
                className="flex flex-wrap justify-between gap-3 border-t border-line px-4 py-2 text-sm first:border-t-0"
              >
                <span>
                  <span className="font-mono">{tool.tool}</span>{" "}
                  <span className="text-xs text-fg-muted">
                    {tool.server} · {t(`toolAccess.${tool.access}` as "toolAccess.read")}
                  </span>
                </span>
                <span className="text-xs">
                  {tool.may_use ? t("mayUse") : t("mayNotUse")}
                  {tool.may_approve ? ` · ${t("mayApprove")}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="m-0 text-xs text-fg-muted">{t("toolsHint")}</p>
      </section>

      {canEdit && g.source !== "keycloak" ? (
        <div>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() =>
              run(
                () => api(`/v1/admin/groups/${g.id}`, { method: "DELETE" }),
                t("deleted"),
                () => router.push("/admin/users"),
              )
            }
          >
            {t("deleteGroup")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
