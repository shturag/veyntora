"use client";

import { Button } from "@veyntora/ui";

import { api } from "@/lib/chat";

import { Result, useAction } from "../evaluation/evaluation-actions";

export function StartReview({ allowed }: { allowed: boolean }) {
  const state = useAction("accessReviews");
  return (
    <span className="flex items-center gap-2">
      <Button
        variant="primary"
        disabled={!allowed || state.busy}
        onClick={() =>
          state.run(
            () => api("/v1/admin/access-reviews", { method: "POST", body: "{}" }),
            state.t("started"),
          )
        }
      >
        {state.t("start")}
      </Button>
      <Result message={state.message} />
    </span>
  );
}

export function CloseReview({ id, undecided }: { id: string; undecided: number }) {
  const state = useAction("accessReviews");
  return (
    <span className="flex items-center gap-2">
      <Button
        disabled={state.busy}
        onClick={() =>
          // Closing ends the round for everyone; undecided access stays as it is.
          window.confirm(state.t("confirmClose", { count: undecided })) &&
          state.run(
            () => api(`/v1/admin/access-reviews/${id}/close`, { method: "POST" }),
            state.t("closed"),
          )
        }
      >
        {state.t("close")}
      </Button>
      <Result message={state.message?.ok ? null : state.message} />
    </span>
  );
}

export function Decide({ id, label }: { id: string; label: string }) {
  const state = useAction("accessReviews");
  const { t } = state;
  const go = (decision: "keep" | "revoke") =>
    state.run(
      () =>
        api(`/v1/admin/access-reviews/items/${id}`, {
          method: "POST",
          body: JSON.stringify({ decision }),
        }),
      t(decision === "keep" ? "kept" : "revoked"),
    );
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        disabled={state.busy}
        aria-label={t("keepLabel", { label })}
        onClick={() => go("keep")}
      >
        {t("keep")}
      </Button>
      <Button
        size="sm"
        variant="danger"
        disabled={state.busy}
        aria-label={t("revokeLabel", { label })}
        onClick={() => go("revoke")}
      >
        {t("revoke")}
      </Button>
      <Result message={state.message?.ok ? null : state.message} />
    </span>
  );
}
