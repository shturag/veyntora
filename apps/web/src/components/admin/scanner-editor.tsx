"use client";

import { Badge, Button } from "@veyntora/ui";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import type { components } from "@/lib/api/schema";
import { api } from "@/lib/chat";

type Scanner = components["schemas"]["ScannerOut"];
type Check = components["schemas"]["CheckOut"];

const input = "h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm";
const label = "flex flex-col gap-1 text-[13px] font-medium";

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
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
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
      </div>
      {!scanner.address && scanner.required ? (
        <p role="note" className="m-0 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">
          {t("requiredNote")}
        </p>
      ) : null}
      <form onSubmit={save} className="flex flex-col gap-3">
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
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy || !address}>
              {scanner.address ? t("save") : t("setUp")}
            </Button>
            {scanner.address ? (
              <Button
                type="button"
                size="sm"
                variant="danger-outline"
                onClick={remove}
                disabled={busy}
                className="ml-auto"
              >
                {t("remove")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {message ? (
          <p
            role={message.ok ? "status" : "alert"}
            className={`m-0 text-sm ${message.ok ? "text-green" : "text-red"}`}
          >
            {message.text}
          </p>
        ) : null}
      </form>
    </section>
  );
}
