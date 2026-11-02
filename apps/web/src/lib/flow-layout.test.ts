import { describe, expect, it } from "vitest";

import { COL_W, ROW_H, layoutFlow, needsLayout } from "./flow-layout";
import { describeProblem } from "./problems";

// The standard pipeline as the API stores it.
const STEPS = [
  "input",
  "router",
  "retriever",
  "reranker",
  "llm",
  "agent_llm",
  "tools",
  "guardrail",
  "output",
].map((id) => ({ id }));
const LINKS = [
  ["input", "router"],
  ["router", "retriever"],
  ["retriever", "reranker"],
  ["reranker", "llm"],
  ["llm", "guardrail"],
  ["router", "agent_llm"],
  ["agent_llm", "tools"],
  ["tools", "agent_llm"],
  ["agent_llm", "guardrail"],
  ["guardrail", "output"],
].map(([source, target]) => ({ source: source!, target: target! }));

describe("flow layout", () => {
  const at = layoutFlow(STEPS, LINKS);

  it("goes top to bottom by the longest path, ignoring the agent's tool loop", () => {
    const col = (id: string) => at[id]!.y / ROW_H;
    expect(col("input")).toBe(0);
    expect(col("router")).toBe(1);
    expect(col("retriever")).toBe(2);
    expect(col("agent_llm")).toBe(2);
    // The agent's tools sit beside it: the loop is drawn as one two-way arrow.
    expect(col("tools")).toBe(2);
    expect(at.tools!.x).toBeGreaterThan(at.agent_llm!.x);
    expect(col("llm")).toBe(4);
    expect(col("guardrail")).toBe(5);
    expect(col("output")).toBe(6);
  });

  it("never puts two steps on the same spot", () => {
    const spots = new Set(Object.values(at).map((p) => `${p.x},${p.y}`));
    expect(spots.size).toBe(STEPS.length);
    expect(Math.min(...Object.values(at).map((p) => p.x))).toBe(0);
    // Fast, Agent and its tools side by side: three steps wide at most.
    const xs = Object.values(at).map((p) => p.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBeLessThanOrEqual(2 * COL_W);
  });

  it("knows when saved positions are useless", () => {
    expect(
      needsLayout([
        { x: 0, y: 0 },
        { x: 0, y: 0 },
      ]),
    ).toBe(true);
    expect(needsLayout([{}, {}])).toBe(true);
    expect(
      needsLayout([
        { x: 0, y: 0 },
        { x: 260, y: 0 },
      ]),
    ).toBe(false);
  });
});

describe("publish checks in people's words", () => {
  it("links each check to the page that fixes it", () => {
    expect(describeProblem("ingestion.parser_instance_id is not set", "b")).toEqual({
      kind: "missing",
      section: "ingestion",
      field: "parser_instance_id",
      href: "/admin/pipelines/b/ingestion",
    });
    expect(describeProblem("retrieval.vector_store_instance_id is not set", "b")).toMatchObject({
      href: "/admin/pipelines/b",
    });
    expect(describeProblem("generation.system_prompt is empty", "b")).toMatchObject({
      kind: "known",
      key: "systemPrompt",
    });
    expect(describeProblem("Generate: this step leads nowhere", "b")).toMatchObject({
      kind: "flow",
      href: "/admin/chatbots/b/flow",
    });
    expect(
      describeProblem(
        "Cloud embeddings is an external provider; allow it in this chatbot's data rules first",
        "b",
      ),
    ).toEqual({ kind: "dataRule", name: "Cloud embeddings", href: "/admin/chatbots/b/access" });
    expect(describeProblem("something new", "b")).toEqual({ kind: "other", text: "something new" });
  });
});
