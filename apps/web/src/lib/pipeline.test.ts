import { describe, expect, it } from "vitest";

import { SECTIONS } from "./pipeline";

describe("pipeline settings sections", () => {
  it("show every field once, under one sub-heading", () => {
    for (const s of SECTIONS) {
      const grouped = s.groups.flatMap(([, names]) => names);
      expect([...grouped].sort(), s.key).toEqual(s.fields.map((f) => f.name).sort());
      expect(new Set(grouped).size, s.key).toBe(grouped.length);
    }
  });
});
