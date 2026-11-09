"use client";

import { useEffect } from "react";

/** Scrolls the open entry into view inside the scrolling list, e.g. after a reload with ?id=. */
export function KeepInView({ list, current }: { list: string; current: string | undefined }) {
  useEffect(() => {
    if (!current) return;
    const box = document.getElementById(list);
    const row = box?.querySelector<HTMLElement>('[aria-current="true"]')?.closest("tr");
    if (!box || !row) return;
    const top = row.offsetTop - box.clientHeight / 2 + row.offsetHeight / 2;
    if (
      row.offsetTop < box.scrollTop ||
      row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight
    )
      box.scrollTo({ top });
  }, [list, current]);
  return null;
}
