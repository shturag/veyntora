import { describe, expect, it } from "vitest";

import { sidebarLayout } from "./sidebar-layout";

const SIZE = { min: 200, max: 360, initial: 240 };

describe("sidebarLayout", () => {
  it("reads the width and whether the sidebar is folded", () => {
    expect(sidebarLayout("300", SIZE)).toEqual({ width: 300, collapsed: false });
    expect(sidebarLayout("280c", SIZE)).toEqual({ width: 280, collapsed: true });
  });

  it("keeps the width within bounds and ignores anything else", () => {
    expect(sidebarLayout("9999", SIZE).width).toBe(360);
    expect(sidebarLayout("50", SIZE).width).toBe(200);
    expect(sidebarLayout(undefined, SIZE)).toEqual({ width: 240, collapsed: false });
    expect(sidebarLayout("wide;x", SIZE)).toEqual({ width: 240, collapsed: false });
  });
});
