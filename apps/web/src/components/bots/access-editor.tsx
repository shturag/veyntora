"use client";

import { Badge, Button, cn } from "@veyntora/ui";
import { Search, Users, User, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Panel, SaveMessage, checkbox } from "@/components/admin/panel";
import { useStepForm } from "@/components/step-forms";
import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Option = components["schemas"]["PrincipalOption"];
type Preview = components["schemas"]["PreviewBot"];
const ROLES = ["user", "approver", "editor", "owner"] as const;
type Role = (typeof ROLES)[number];
type Row = { principal: string; name: string; roles: Role[] };

const search =
  "h-10 w-full rounded-md border border-line-strong bg-surface pr-3 pl-9 text-sm font-normal";

/** Groups and people matching what was typed (debounced). */
function usePrincipals(botId: string, q: string): Option[] {
  const [found, setFound] = useState<Option[]>([]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void api<Option[]>(`/v1/admin/chatbots/${botId}/principals?q=${encodeURIComponent(q.trim())}`)
        .then(setFound)
        .catch(() => setFound([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, botId]);
  return found;
}

function SearchField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px] font-medium">
      {label}
      <span className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted"
        />
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={search}
        />
      </span>
    </label>
  );
}

function Who({ principal, name }: { principal: string; name: string }) {
  const t = useTranslations("bots");
  const group = principal.startsWith("group:");
  const Icon = group ? Users : User;
  return (
    <span className="flex min-w-0 items-center gap-3">
      <span
        aria-hidden
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
      >
        <Icon className="size-4" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{name}</span>
        <span className="text-xs text-fg-muted">{group ? t("aGroup") : t("aPerson")}</span>
      </span>
    </span>
  );
}

/** Who may use the chatbot and how; and a read-only preview of a person's access. */
export function AccessEditor({
  botId,
  grants,
  names,
  canEdit,
}: {
  botId: string;
  grants: { principal: string; role: string }[];
  names: Record<string, string>;
  canEdit: boolean;
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
  const [dirty, setDirty] = useState(false);
  const [q, setQ] = useState("");
  const found = usePrincipals(botId, q);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  function change(update: (list: Row[]) => Row[]) {
    setRows(update);
    setDirty(true);
    setMessage(null);
  }

  async function persist() {
    await api(`/v1/admin/chatbots/${botId}/access`, {
      method: "PUT",
      body: JSON.stringify(
        rows.flatMap((r) => r.roles.map((role) => ({ principal: r.principal, role }))),
      ),
    });
    setDirty(false);
  }
  // In the wizard, the step saves this with the other panels.
  const inStep = useStepForm("access", dirty, persist);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await persist();
      setMessage({ ok: true, text: t("saved") });
      router.refresh();
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
    change((list) =>
      list.map((r, j) =>
        j === i
          ? {
              ...r,
              roles: on ? [...new Set([...r.roles, role])] : r.roles.filter((x) => x !== role),
            }
          : r,
      ),
    );
  const addable = q.trim()
    ? found.filter((o) => !rows.some((r) => r.principal === o.principal)).slice(0, 8)
    : [];

  return (
    <div className="grid grid-cols-[minmax(0,2fr)_minmax(300px,1fr)] items-start gap-5 max-[1100px]:grid-cols-1">
      <Panel
        id="ac-title"
        title={t("whoCanUse")}
        description={t("accessIntro")}
        footer={
          canEdit && !inStep ? (
            <>
              <SaveMessage message={message} />
              {dirty && !message ? (
                <span className="text-sm text-fg-muted">{t("unsaved")}</span>
              ) : null}
              <Button variant="primary" disabled={busy} onClick={save}>
                {t("save")}
              </Button>
            </>
          ) : null
        }
      >
        <div className="relative overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="bg-sunken text-left text-xs font-semibold text-fg-muted">
                <th scope="col" className="px-4 py-2.5 font-semibold">
                  {t("whoCol")}
                </th>
                {ROLES.map((role) => (
                  <th key={role} scope="col" className="px-3 py-2.5 text-center font-semibold">
                    {t(`roles.${role}`)}
                  </th>
                ))}
                <th scope="col" className="w-12 px-2">
                  <span className="sr-only">{t("remove")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={ROLES.length + 2} className="px-4 py-6 text-center text-fg-muted">
                    {t("nobodyYet")}
                  </td>
                </tr>
              ) : null}
              {rows.map((r, i) => (
                <tr key={r.principal} className="border-t border-line">
                  <td className="px-4 py-3">
                    <Who principal={r.principal} name={r.name} />
                  </td>
                  {ROLES.map((role) => (
                    <td key={role} className="px-3 py-3 text-center">
                      <input
                        type="checkbox"
                        aria-label={`${t(`roles.${role}`)}: ${r.name}`}
                        checked={r.roles.includes(role)}
                        disabled={!canEdit}
                        onChange={(e) => toggle(i, role, e.target.checked)}
                        className={cn(checkbox, "mt-0")}
                      />
                    </td>
                  ))}
                  <td className="px-2 py-3 text-right">
                    {canEdit ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t("removeWho", { name: r.name })}
                        title={t("removeWho", { name: r.name })}
                        onClick={() => change((list) => list.filter((_, j) => j !== i))}
                        className="size-8 px-0"
                      >
                        <X aria-hidden className="size-4" />
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canEdit ? (
          <div className="flex flex-col gap-2">
            <SearchField
              label={t("addWho")}
              value={q}
              onChange={setQ}
              placeholder={t("addWhoHint")}
            />
            {q.trim() ? (
              addable.length === 0 ? (
                <p className="m-0 text-sm text-fg-muted">{t("noPrincipalMatch")}</p>
              ) : (
                <ul className="m-0 flex list-none flex-col rounded-md border border-line p-0">
                  {addable.map((o) => (
                    <li
                      key={o.principal}
                      className="flex items-center justify-between gap-3 border-t border-line px-4 py-2 first:border-t-0"
                    >
                      <Who principal={o.principal} name={o.name} />
                      <Button
                        size="sm"
                        onClick={() => {
                          change((list) => [
                            ...list,
                            { principal: o.principal, name: o.name, roles: ["user"] },
                          ]);
                          setQ("");
                        }}
                      >
                        {t("add")}
                      </Button>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </div>
        ) : null}
      </Panel>
      <PreviewPanel botId={botId} />
    </div>
  );
}

/** Which chatbots one person sees, and with which roles; nobody is signed in as them. */
function PreviewPanel({ botId }: { botId: string }) {
  const t = useTranslations("bots");
  const [q, setQ] = useState("");
  const found = usePrincipals(botId, q);
  const [previewFor, setPreviewFor] = useState<Option | null>(null);
  const [preview, setPreview] = useState<Preview[] | null>(null);
  const people = q.trim() ? found.filter((o) => o.principal.startsWith("user:")).slice(0, 6) : [];

  async function show(person: Option) {
    setPreviewFor(person);
    setPreview(null);
    setQ("");
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

  return (
    <Panel id="pv-title" title={t("previewTitle")} description={t("previewHint")}>
      <SearchField
        label={t("previewPerson")}
        value={q}
        onChange={setQ}
        placeholder={t("previewPlaceholder")}
      />
      {people.length > 0 ? (
        <ul className="m-0 flex list-none flex-col rounded-md border border-line p-0">
          {people.map((p) => (
            <li key={p.principal} className="border-t border-line first:border-t-0">
              <button
                type="button"
                onClick={() => show(p)}
                className="flex w-full items-center px-3 py-2 text-left text-sm hover:bg-sunken"
              >
                <Who principal={p.principal} name={p.name} />
              </button>
            </li>
          ))}
        </ul>
      ) : q.trim() ? (
        <p className="m-0 text-sm text-fg-muted">{t("noPrincipalMatch")}</p>
      ) : null}
      {previewFor ? (
        <div className="flex flex-col gap-2 rounded-md bg-sunken p-3">
          <span className="text-sm font-semibold">{previewFor.name}</span>
          {preview === null ? (
            <span className="text-sm text-fg-muted">…</span>
          ) : preview.length === 0 ? (
            <p className="m-0 text-sm text-fg-secondary">
              {t("previewNone", { name: previewFor.name })}
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
              {preview.map((b) => (
                <li key={b.chatbot_id} className="flex flex-col gap-1">
                  <span className="font-medium">
                    {b.chatbot}
                    {b.live ? null : (
                      <span className="font-normal text-fg-muted"> · {t("notLive")}</span>
                    )}
                  </span>
                  <span className="flex flex-wrap gap-1">
                    {b.roles.map((r) => (
                      <Badge key={r} tone="accent">
                        {t(`roles.${r}` as "roles.user")}
                      </Badge>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="m-0 text-sm text-fg-muted">{t("previewSearch")}</p>
      )}
    </Panel>
  );
}
