import { useEffect, useRef, useState } from "react";

// Characters per second: CATCH_UP times the backlog, between MIN_RATE and MAX_RATE. Text the
// model streams keeps up with it; a whole answer arriving at once (held for a guardrail
// check) types out at reading pace (about 4 s for 1,000 characters), not in one jump.
const MIN_RATE = 40;
const MAX_RATE = 250;
const CATCH_UP = 2;

function reducedMotion(): boolean {
  return (
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * `target` as it should read on screen: revealed at a steady pace while `enabled`, starting
 * at `from` characters. When the target shrinks (a new draft), the reveal starts over from
 * there. With reduced motion, or not `enabled`, the target as is.
 */
export function useSmoothText(target: string, enabled = true, from = 0): string {
  const [shown, setShown] = useState(from);
  const shownRef = useRef(from);
  const targetRef = useRef(target);

  useEffect(() => {
    targetRef.current = target;
  }, [target]);

  useEffect(() => {
    if (!enabled || reducedMotion()) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const goal = targetRef.current.length;
      const dt = Math.min(now - last, 100) / 1000;
      last = now;
      let next = Math.min(shownRef.current, goal);
      const backlog = goal - next;
      if (backlog > 0)
        next = Math.min(
          goal,
          next + Math.max(1, Math.min(MAX_RATE, Math.max(MIN_RATE, backlog * CATCH_UP)) * dt),
        );
      if (next !== shownRef.current) {
        shownRef.current = next;
        setShown(next);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [enabled]);

  if (!enabled || reducedMotion()) return target;
  return target.slice(0, Math.floor(Math.min(shown, target.length)));
}
