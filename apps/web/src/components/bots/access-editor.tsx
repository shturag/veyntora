"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Option = components["schemas"]["PrincipalOption"];
type Preview = components["schemas"]["PreviewBot"];
const ROLES = ["user", "approver", "editor", "owner"] as const;
type Role = (typeof ROLES)[number];
type Row = { principal: string; name: string; roles: Role[] };

/** Who may use the chatbot and how; and a read-only preview of a person's access. */
export function AccessEditor({
  botId,
  grants,
  names,
  canEdit,
  next,
}: {
  botId: string;
  grants: { principal: string; role: string }[];
  names: Record<string, string>;
  canEdit: boolean;
  next?: string;
}) {
  const t = useTranslations("bots");
  const router = useRouter();
  const initial = new Map<string, Row>();
  for (const g of grants) {
    const row = initial.get(g.principal) ?? {
      principal: g.principal,
      name: names[g.principal] ?? g.principal,
      roles: [],
    };
    row.roles.push(g.role as Role);
    initial.set(g.principal, row);
  }
  const [rows, setRows] = useState<Row[]>([...initial.values()]);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Option[]>([]);
  const [previewFor, setPreviewFor] = useState<Option | null>(null);
  const [preview, setPreview] = useState<Preview[] | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void api<Option[]>(`/v1/admin/chatbots/${botId}/principals?q=${encodeURIComponent(q.trim())}`)
        .then(setFound)
        .catch(() => setFound([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, botId]);

  async function showPreview(person: Option) {
    setPreviewFor(person);
    setPreview(null);
    try {
      setPreview(
        await api<Preview[]>(
          `/v1/admin/chatbots/${botId}/preview?user_id=${person.principal.slice(5)}`,
        ),
      );
    } catch {
      setPreview([]);
    }
  }

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api(`/v1/admin/chatbots/${botId}/access`, {
        method: "PUT",
        body: JSON.stringify(
          rows.flatMap((r) => r.roles.map((role) => ({ principal: r.principal, role }))),
        ),
      });
      if (next) router.push(next);
      else {
        setMessage({ ok: true, text: t("saved") });
        router.refresh();
      }
    } catch (e) {
      setMessage({
        ok: false,
        text: t("failed", { reason: e instanceof Error ? e.message : "?" }),
      });
    } finally {
      setBusy(false);
    }
  }

  const toggle = (i: number, role: Role, on: boolean) =>
    setRows((list) =>
      list.map((r, j) =>
        j === i
          ? {
              ...r,
              roles: on ? [...new Set([...r.roles, role])] : r.roles.filter((x) => x !== role),
            }
          : r,
      ),
    );
  const people = found.filter((o) => o.principal.startsWith("user:"));

  return (
    <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)] items-start gap-5 max-[1000px]:grid-cols-1">
      <section aria-labelledby="ac-title" className="flex flex-col gap-3">
        <h2 id="ac-title" className="m-0 text-base font-semibold">
          {t("whoCanUse")}
        </h2>
        <p className="m-0 text-sm text-fg-secondary">{t("accessIntro")}</p>
        <ul className="m-0 flex list-none flex-col rounded-lg border border-line bg-surface p-0">
          {rows.length === 0 ? (
            <li className="px-4 py-3 text-sm text-fg-muted">{t("nobody")}</li>
          ) : null}
          {rows.map((r, i) => (
            <li
              key={r.principal}
              className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5 text-sm first:border-t-0"
            >
              <span className="min-w-44 font-medium">
                {r.name}{" "}
                <span className="text-xs font-normal text-fg-muted">
                  {r.principal.startsWith("group:") ? t("aGroup") : t("aPerson")}
                </span>
              </span>
              {ROLES.map((role) => (
                <label key={role} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={r.roles.includes(role)}
                    disabled={!canEdit}
                    onChange={(e) => toggle(i, role, e.target.checked)}
                  />
                  {t(`roles.${role}`)}
                </label>
              ))}
              {canEdit ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setRows((list) => list.filter((_, j) => j !== i))}
                >
                  {t("remove")}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        {canEdit ? (
          <div className="flex flex-col gap-2">
            <label className="flex flex-col gap-1 text-[13px] font-medium">
              {t("addWho")}
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t("addWhoHint")}
                className="h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal"
              />
            </label>
            <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
              {found
                .filter((o) => !rows.some((r) => r.principal === o.principal))
                .slice(0, 12)
                .map((o) => (
                  <li key={o.principal}>
                    <Button
                      size="sm"
                      onClick={() =>
                        setRows((list) => [
                          ...list,
                          { principal: o.principal, name: o.name, roles: ["user"] },
                        ])
                      }
                    >
                      + {o.name}
                    </Button>
                  </li>
                ))}
            </ul>
            <div className="flex items-center gap-3">
              <Button variant="primary" disabled={busy} onClick={save}>
                {next ? t("saveContinue") : t("save")}
              </Button>
              {message ? (
                <span
                  role={message.ok ? "status" : "alert"}
                  className={`text-sm ${message.ok ? "text-green" : "text-red"}`}
                >
                  {message.text}
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>
      <section
        aria-labelledby="pv-title"
        className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4"
      >
        <h2 id="pv-title" className="m-0 text-base font-semibold">
          {t("previewTitle")}
        </h2>
        <p className="m-0 text-xs text-fg-muted">{t("previewHint")}</p>
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
          {people.slice(0, 8).map((p) => (
            <li key={p.principal}>
              <Button
                size="sm"
                variant={previewFor?.principal === p.principal ? "primary" : "secondary"}
                onClick={() => showPreview(p)}
              >
                {p.name}
              </Button>
            </li>
          ))}
        </ul>
        {people.length === 0 ? (
          <p className="m-0 text-xs text-fg-muted">{t("previewSearch")}</p>
        ) : null}
        {previewFor && preview ? (
          preview.length === 0 ? (
            <p className="m-0 text-sm">{t("previewNone", { name: previewFor.name })}</p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm">
              {preview.map((b) => (
                <li key={b.chatbot_id}>
                  <span className="font-medium">{b.chatbot}</span> ·{" "}
                  {b.roles.map((r) => t(`roles.${r}` as "roles.user")).join(", ")}
                  {b.live ? "" : ` · ${t("notLive")}`}
                </li>
              ))}
            </ul>
          )
        ) : null}
      </section>
    </div>
  );
}
