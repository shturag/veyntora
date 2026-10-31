"use client";

import { Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/chat";

import { PersonPicker } from "./person-picker";

type Op = "equals" | "not_equals" | "in" | "at_least" | "at_most" | "exists";
type Condition = { attribute: string; op: Op; value: string };
const OPS: Op[] = ["equals", "not_equals", "in", "at_least", "at_most", "exists"];
const field = "flex flex-col gap-1 text-[13px] font-medium";
const control = "h-10 rounded-md border border-line-strong bg-surface px-3 text-sm font-normal";

function value(c: Condition): string | number | string[] | null {
  if (c.op === "exists") return null;
  if (c.op === "in")
    return c.value
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  if (c.op === "at_least" || c.op === "at_most") return Number(c.value);
  return c.value.trim();
}

/** Basics, then who is in it: a manual list or a rule on Keycloak attributes. */
export function NewGroupForm() {
  const t = useTranslations("people");
  const router = useRouter();
  const [source, setSource] = useState<"manual" | "rule">("manual");
  const [members, setMembers] = useState<{ id: string; name: string }[]>([]);
  const [match, setMatch] = useState<"all" | "any">("all");
  const [conditions, setConditions] = useState<Condition[]>([
    { attribute: "department", op: "equals", value: "" },
  ]);
  const [expires, setExpires] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const group = await api<{ id: string }>("/v1/admin/groups", {
        method: "POST",
        body: JSON.stringify({
          name: String(f.get("name")),
          description: String(f.get("description") || ""),
          source,
          rule:
            source === "rule"
              ? {
                  match,
                  conditions: conditions.map((c) => ({
                    attribute: c.attribute.trim(),
                    op: c.op,
                    value: value(c),
                  })),
                }
              : null,
          members:
            source === "manual"
              ? members.map((m) => ({
                  user_id: m.id,
                  expires_at: expires ? `${expires}T23:59:59Z` : null,
                }))
              : [],
        }),
      });
      router.push(`/admin/groups/${group.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  const set = (i: number, patch: Partial<Condition>) =>
    setConditions((list) => list.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  return (
    <form
      aria-label={t("newGroupTitle")}
      onSubmit={submit}
      className="flex flex-col gap-5 rounded-lg border border-line bg-surface p-5"
    >
      <h2 className="m-0 text-base font-semibold">1. {t("basics")}</h2>
      <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
        <label className={field}>
          {t("groupName")}
          <input name="name" required maxLength={255} className={control} />
        </label>
        <label className={field}>
          {t("description")}
          <input name="description" maxLength={2000} className={control} />
        </label>
      </div>
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-1 p-0 text-base font-semibold">2. {t("whoIsIn")}</legend>
        <p className="m-0 text-xs text-fg-muted">{t("keycloakAuto")}</p>
        {(["manual", "rule"] as const).map((s) => (
          <label key={s} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="source"
              checked={source === s}
              onChange={() => setSource(s)}
            />
            {t(`newSources.${s}`)}
          </label>
        ))}
      </fieldset>
      {source === "manual" ? (
        <div className="flex flex-col gap-2">
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {members.map((m) => (
              <li
                key={m.id}
                className="flex items-center gap-1 rounded-full border border-line-strong px-2.5 py-0.5 text-sm"
              >
                {m.name}
                <button
                  type="button"
                  aria-label={t("removeName", { name: m.name })}
                  onClick={() => setMembers((l) => l.filter((x) => x.id !== m.id))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-end gap-3">
            <PersonPicker
              label={t("addPerson")}
              value={null}
              onChange={(p) =>
                p && !members.some((m) => m.id === p.id) && setMembers((l) => [...l, p])
              }
            />
            <label className={field}>
              {t("membershipEnds")}
              <input
                type="date"
                value={expires}
                onChange={(e) => setExpires(e.target.value)}
                className={control}
              />
            </label>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <label className="flex items-center gap-2 text-sm">
            {t("includeWhere")}
            <select
              value={match}
              onChange={(e) => setMatch(e.target.value as "all" | "any")}
              className={control}
            >
              <option value="all">{t("matchAll")}</option>
              <option value="any">{t("matchAny")}</option>
            </select>
          </label>
          {conditions.map((c, i) => (
            <div key={i} className="flex flex-wrap items-end gap-2">
              <label className={field}>
                {t("attribute")}
                <input
                  value={c.attribute}
                  onChange={(e) => set(i, { attribute: e.target.value })}
                  required
                  className={control}
                />
              </label>
              <label className={field}>
                {t("operator")}
                <select
                  value={c.op}
                  onChange={(e) => set(i, { op: e.target.value as Op })}
                  className={control}
                >
                  {OPS.map((o) => (
                    <option key={o} value={o}>
                      {t(`ops.${o}`)}
                    </option>
                  ))}
                </select>
              </label>
              {c.op !== "exists" ? (
                <label className={field}>
                  {t("value")}
                  <input
                    value={c.value}
                    onChange={(e) => set(i, { value: e.target.value })}
                    required
                    className={control}
                  />
                </label>
              ) : null}
              {conditions.length > 1 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConditions((l) => l.filter((_, j) => j !== i))}
                >
                  {t("remove")}
                </Button>
              ) : null}
            </div>
          ))}
          <div>
            <Button
              size="sm"
              onClick={() =>
                setConditions((l) => [...l, { attribute: "", op: "equals", value: "" }])
              }
            >
              {t("addRule")}
            </Button>
          </div>
          <p className="m-0 text-xs text-fg-muted">{t("ruleHint")}</p>
        </div>
      )}
      <p className="m-0 text-sm text-fg-secondary">3. {t("rolesNext")}</p>
      {error ? (
        <p role="alert" className="m-0 text-sm text-red">
          {t("failed", { reason: error })}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant="primary" disabled={busy}>
          {t("createGroup")}
        </Button>
      </div>
    </form>
  );
}
