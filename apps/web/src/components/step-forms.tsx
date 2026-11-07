"use client";

import { Button } from "@veyntora/ui";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Entry = { dirty: boolean; save: () => Promise<void> };
type Register = (id: string, entry: Entry | null) => void;

const StepContext = createContext<Register | null>(null);

/**
 * A panel's part in a wizard step: the step saves it with the others. Returns whether the panel
 * is inside a step (then it shows no Save button of its own). `save` throws when it fails.
 */
export function useStepForm(id: string, dirty: boolean, save: () => Promise<void>): boolean {
  const register = useContext(StepContext);
  const latest = useRef(save);
  useEffect(() => {
    latest.current = save;
  });
  useEffect(() => {
    if (!register) return;
    register(id, { dirty, save: () => latest.current() });
    return () => register(id, null);
  }, [register, id, dirty]);
  return register !== null;
}

/** Several panels saved by one "Save and continue" at the end of a wizard step. */
export function StepForms({
  next,
  hint,
  saveLabel,
  unsavedLabel,
  children,
}: {
  next: string;
  hint: string;
  saveLabel: string;
  unsavedLabel: string;
  children: ReactNode;
}) {
  const router = useRouter();
  const entries = useRef(new Map<string, Entry>());
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const register = useCallback<Register>((id, entry) => {
    if (entry) entries.current.set(id, entry);
    else entries.current.delete(id);
    setDirty([...entries.current.values()].some((e) => e.dirty));
  }, []);

  async function saveAll() {
    setBusy(true);
    setError(null);
    try {
      for (const e of entries.current.values()) if (e.dirty) await e.save();
      router.push(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "?");
      setBusy(false);
    }
  }

  return (
    <StepContext.Provider value={register}>
      {children}
      <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-5 py-4 shadow-md">
        <span className="text-sm text-fg-secondary">
          {error ? (
            <span role="alert" className="text-red">
              {error}
            </span>
          ) : dirty ? (
            unsavedLabel
          ) : (
            hint
          )}
        </span>
        <Button variant="primary" disabled={busy} onClick={saveAll}>
          {saveLabel}
        </Button>
      </div>
    </StepContext.Provider>
  );
}
