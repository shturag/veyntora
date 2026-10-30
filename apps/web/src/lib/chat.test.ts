import { describe, expect, it } from "vitest";

import { parseAnswer, textOf } from "./chat";

describe("parseAnswer", () => {
  it("splits paragraphs, bold text and citations", () => {
    expect(parseAnswer("Refunds take **14 days** [1].\n\nSubscriptions differ [2, 3].")).toEqual([
      [
        { kind: "text", text: "Refunds take " },
        { kind: "bold", text: "14 days" },
        { kind: "text", text: " " },
        { kind: "cite", n: 1 },
        { kind: "text", text: "." },
      ],
      [
        { kind: "text", text: "Subscriptions differ " },
        { kind: "cite", n: 2 },
        { kind: "cite", n: 3 },
        { kind: "text", text: "." },
      ],
    ]);
  });

  it("never turns markup into HTML", () => {
    expect(parseAnswer("<img src=x onerror=alert(1)>")).toEqual([
      [{ kind: "text", text: "<img src=x onerror=alert(1)>" }],
    ]);
  });

  it("reads string and part-list message content", () => {
    expect(textOf("hi")).toBe("hi");
    expect(textOf([{ type: "text", text: "a" }, "b"])).toBe("ab");
    expect(textOf(null)).toBe("");
  });
});
