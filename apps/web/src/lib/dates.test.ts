import { describe, expect, it } from "vitest";

import { sameText } from "./dates";

describe("dates formatted by different engines", () => {
  it("read the same", () => {
    expect(sameText("Nov 9, 2026, 10:58\u202fPM")).toBe("Nov 9, 2026, 10:58 PM");
    expect(sameText("Nov 9, 2026 at 10:58 PM")).toBe("Nov 9, 2026, 10:58 PM");
    expect(sameText("9. Nov. 2026 um 22:58")).toBe("9. Nov. 2026, 22:58");
    expect(sameText("Mo., 9. Nov., 22:58")).toBe(sameText("Mo. 9. Nov., 22:58"));
    expect(sameText("Nov 9, 2026")).toBe("Nov 9, 2026");
    expect(sameText("Meet at noon")).toBe("Meet at noon");
  });
});
