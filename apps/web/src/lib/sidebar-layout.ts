/** The sidebar's remembered size: a cookie per sidebar, "<width>" or "<width>c" (folded). */
export const SIDEBAR_COOKIE = "vey_sidebar_";

export type SidebarLayout = { width: number; collapsed: boolean };

export function sidebarLayout(
  raw: string | undefined,
  { min, max, initial }: { min: number; max: number; initial: number },
): SidebarLayout {
  const match = /^(\d{2,4})(c?)$/.exec(raw ?? "");
  const width = match ? Number(match[1]) : initial;
  return { width: Math.min(max, Math.max(min, width)), collapsed: match?.[2] === "c" };
}
