"use client";

import { Badge, Button } from "@veyntora/ui";
import { ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Scanner = components["schemas"]["ScannerOut"];
type Check = components["schemas"]["CheckOut"];

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";
const sectionTitle = "m-0 text-xs font-semibold tracking-wide text-fg-muted uppercase";

/** The virus scanner (clamd) uploads are checked with: its address and "Test connection". */
export function ScannerEditor({ scanner, canEdit }: { scanner: Scanner; canEdit: boolean }) {
  const t = useTranslations("integrations.scanner");
  const router = useRouter();
  const [address, setAddress] = useState(scanner.address ?? "");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<{ ok: boolean; text: string }>) {
    setBusy(true);
    setMessage(null);
    try {
      setMessage(await action());
      router.refresh();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : t("failed") });
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      await api("/v1/admin/scanner", { method: "PUT", body: JSON.stringify({ address }) });
      return { ok: true, text: t("saved") };
    });
  }

  const test = () =>
    run(async () => {
      const res = await api<Check>("/v1/admin/scanner/test", {
        method: "POST",
        body: JSON.stringify({ address }),
      });
      return {
        ok: res.ok,
        text: res.ok ? t("reachable") : t("unreachable", { detail: res.detail }),
      };
    });

  const remove = () =>
    run(async () => {
      await api("/v1/admin/scanner", { method: "DELETE" });
      setAddress("");
      return { ok: true, text: t("removed") };
    });

  return (
    <section
      aria-labelledby="scanner-title"
      className="flex flex-col rounded-lg border border-line bg-surface"
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 id="scanner-title" className="m-0 flex items-center gap-2 text-lg font-bold">
            {t("title")}
            <Badge tone={scanner.address ? "green" : scanner.required ? "amber" : "neutral"}>
              {scanner.address ? t("on") : t("notSetUp")}
            </Badge>
          </h2>
          <p className="m-0 text-sm text-fg-secondary">{t("summary")}</p>
        </div>
        {canEdit ? (
          <Button type="button" size="sm" onClick={test} disabled={busy || !address}>
            {t("test")}
          </Button>
        ) : null}
      </header>
      <div className="grid grid-cols-2 max-[1100px]:grid-cols-1">
        <form
          onSubmit={save}
          className="flex flex-col gap-4 p-5 min-[1101px]:border-r min-[1101px]:border-divider"
        >
          <h3 className={sectionTitle}>{t("connection")}</h3>
          <label className={label}>
            {t("address")}
            <input
              name="address"
              required
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="host.docker.internal:3310"
              pattern="[A-Za-z0-9.\-]+:\d{1,5}"
              disabled={!canEdit}
              className={`${input} font-mono`}
            />
            <span className="text-xs font-normal text-fg-muted">{t("addressHint")}</span>
          </label>
          {canEdit ? (
            <div className="mt-auto flex justify-end border-t border-divider pt-4">
              <Button type="submit" variant="primary" disabled={busy || !address}>
                {scanner.address ? t("save") : t("setUp")}
              </Button>
            </div>
          ) : null}
        </form>
        <div className="flex flex-col gap-3 p-5 max-[1100px]:border-t max-[1100px]:border-divider">
          <h3 className={sectionTitle}>{t("policy")}</h3>
          <p className="m-0 flex items-start gap-2 text-sm text-fg-secondary">
            <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
            {scanner.required ? t("requiredOn") : t("requiredOff")}
          </p>
          {!scanner.address && scanner.required ? (
            <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
              {t("requiredNote")}
            </p>
          ) : null}
        </div>
      </div>
      {message || (scanner.address && canEdit) ? (
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
          {message ? (
            <p
              role={message.ok ? "status" : "alert"}
              className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
            >
              {message.text}
            </p>
          ) : (
            <span />
          )}
          {scanner.address && canEdit ? (
            <Button
              type="button"
              size="sm"
              variant="danger-outline"
              onClick={() => {
                if (window.confirm(t("removeConfirm"))) void remove();
              }}
              disabled={busy}
            >
              {t("remove")}
            </Button>
          ) : null}
        </footer>
      ) : null}
    </section>
  );
}
