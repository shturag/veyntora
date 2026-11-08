"use client";

import { useTranslations } from "next-intl";

import { FIELDS, SECRETS, type InfraService, type Values } from "@/lib/infra-fields";

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

/**
 * One service's settings and passwords. Passwords are write-only: with `last4` (a saved
 * service) an empty field keeps the one in use.
 */
export function ServiceFields({
  service,
  values,
  secrets,
  onValue,
  onSecret,
  last4,
  disabled,
  only,
}: {
  service: InfraService;
  values: Values;
  secrets: Record<string, string>;
  onValue: (name: string, value: string | number | boolean) => void;
  onSecret: (name: string, value: string) => void;
  last4?: Record<string, string | null | undefined>;
  disabled?: boolean;
  /** Only the settings or only the passwords, for an editor that shows them in sections. */
  only?: "settings" | "secrets";
}) {
  const t = useTranslations("infra");
  const id = (name: string) => `infra-${service}-${name}`;
  return (
    <div className="grid grid-cols-2 gap-3 max-[640px]:grid-cols-1">
      {(only === "secrets" ? [] : FIELDS[service]).map((f) =>
        f.kind === "bool" ? (
          <label key={f.name} className="col-span-full flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={Boolean(values[f.name])}
              onChange={(e) => onValue(f.name, e.target.checked)}
              disabled={disabled}
            />
            {t(`fields.${service}.${f.name}`)}
          </label>
        ) : (
          <label key={f.name} htmlFor={id(f.name)} className={label}>
            {t(`fields.${service}.${f.name}`)}
            <input
              id={id(f.name)}
              name={f.name}
              type={f.kind === "number" ? "number" : "text"}
              required={f.required}
              value={String(values[f.name] ?? "")}
              placeholder={f.placeholder}
              onChange={(e) => onValue(f.name, e.target.value)}
              disabled={disabled}
              autoComplete="off"
              spellCheck={false}
              className={`${input} ${f.kind === "text" ? "font-mono" : ""}`}
            />
          </label>
        ),
      )}
      {(only === "settings" ? [] : SECRETS[service]).map((s) => {
        const saved = last4 ? last4[s.name] : undefined;
        return (
          <label key={s.name} htmlFor={id(s.name)} className={label}>
            {t(`secrets.${s.name}`)}
            <input
              id={id(s.name)}
              name={s.name}
              type="password"
              value={secrets[s.name] ?? ""}
              onChange={(e) => onSecret(s.name, e.target.value)}
              required={!last4 && !s.optional}
              disabled={disabled}
              autoComplete="new-password"
              placeholder={last4 ? (saved ? t("keepSecret", { last4: saved }) : t("keepSet")) : ""}
              className={input}
            />
          </label>
        );
      })}
    </div>
  );
}
