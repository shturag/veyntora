import { describe, expect, it } from "vitest";

import { parseAnswer, parseBlocks, textOf } from "./chat";

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

describe("parseBlocks", () => {
  it("reads the Markdown models write", () => {
    const blocks = parseBlocks(
      [
        "### 2. Core diagnosis",
        "The document names **six** problems [1]:",
        "1. Finance",
        "2. Energy",
        "",
        "* Mission 1",
        "* Mission 2",
        "  continued",
        "",
        "| Year | Balance |",
        "|---|---|",
        "| 1 | 10,400 |",
        "",
        "```",
        "print(1)",
        "```",
        "Line one",
        "line two with `code`",
      ].join("\n"),
    );
    expect(blocks.map((b) => b.kind)).toEqual([
      "heading",
      "paragraph",
      "list",
      "list",
      "table",
      "code",
      "paragraph",
    ]);
    expect(blocks[0]).toEqual({
      kind: "heading",
      level: 3,
      text: [{ kind: "text", text: "2. Core diagnosis" }],
    });
    expect(blocks[2]).toMatchObject({ kind: "list", ordered: true });
    expect(blocks[3]).toEqual({
      kind: "list",
      ordered: false,
      items: [
        [{ kind: "text", text: "Mission 1" }],
        [
          { kind: "text", text: "Mission 2" },
          { kind: "text", text: " continued" },
        ],
      ],
    });
    expect(blocks[4]).toMatchObject({
      kind: "table",
      rows: [[[{ kind: "text", text: "1" }], [{ kind: "text", text: "10,400" }]]],
    });
    expect(blocks[5]).toEqual({ kind: "code", text: "print(1)" });
    expect(blocks[6]).toMatchObject({
      kind: "paragraph",
      lines: [[{ text: "Line one" }], [{ text: "line two with " }, { kind: "code", text: "code" }]],
    });
  });

  it("reads italics, but not a lone asterisk", () => {
    expect(parseBlocks("Phase I. *Unlocked by:* bank repair, 2 * 3 = 6")).toEqual([
      {
        kind: "paragraph",
        lines: [
          [
            { kind: "text", text: "Phase I. " },
            { kind: "italic", text: "Unlocked by:" },
            { kind: "text", text: " bank repair, 2 * 3 = 6" },
          ],
        ],
      },
    ]);
  });

  it("never turns markup into HTML", () => {
    expect(parseBlocks("# <script>x</script>")).toEqual([
      { kind: "heading", level: 1, text: [{ kind: "text", text: "<script>x</script>" }] },
    ]);
  });
});
