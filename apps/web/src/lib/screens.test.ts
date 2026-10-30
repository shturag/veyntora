import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import { negotiate } from "../i18n/config";
import { ADMIN_NAV, SCREENS, samplePath } from "./screens";

const prototypeDir = fileURLToPath(new URL("../../../../design/prototype", import.meta.url));

function keys(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) return [prefix];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    keys(v, prefix ? `${prefix}.${k}` : k),
  );
}

describe("screen manifest", () => {
  it("covers every prototype screen exactly once", () => {
    const files = readdirSync(prototypeDir)
      .filter((f) => f.endsWith(".html") && f !== "screens.html")
      .sort();
    expect(SCREENS.map((s) => s.file).sort()).toEqual(files);
    expect(new Set(SCREENS.map((s) => s.key)).size).toBe(SCREENS.length);
  });

  it("guards every admin screen with an area", () => {
    for (const s of SCREENS.filter((x) => x.shell === "admin" || x.shell === "wizard")) {
      expect(s.area, s.key).toBeDefined();
      expect(s.route.startsWith("/admin"), s.key).toBe(true);
    }
  });

  it("has an English and German title and summary for every screen", () => {
    for (const s of SCREENS) {
      for (const messages of [en, de]) {
        const entry = (messages.screens as Record<string, { title?: string; summary?: string }>)[s.key];
        expect(entry?.title, s.key).toBeTruthy();
        expect(entry?.summary, s.key).toBeTruthy();
      }
    }
  });

  it("builds sample paths for dynamic routes", () => {
    expect(samplePath("/admin/automations/[id]/agent-step/[stepId]")).toMatch(
      /^\/admin\/automations\/0{8}-[0-9-]+\/agent-step\/0{8}-[0-9-]+$/,
    );
  });

  it("labels every admin nav item in both languages", () => {
    for (const item of ADMIN_NAV.flatMap((g) => g.items)) {
      expect((en.adminNav.items as Record<string, string>)[item.key]).toBeTruthy();
      expect((de.adminNav.items as Record<string, string>)[item.key]).toBeTruthy();
    }
  });
});

describe("i18n", () => {
  it("German and English messages have the same keys", () => {
    expect(keys(de).sort()).toEqual(keys(en).sort());
  });

  it("negotiates the best supported locale", () => {
    expect(negotiate("de-DE,de;q=0.9,en;q=0.8")).toBe("de");
    expect(negotiate("fr-FR,fr;q=0.9,en;q=0.5")).toBe("en");
    expect(negotiate("fr")).toBe("en");
    expect(negotiate(null)).toBe("en");
    expect(negotiate("en;q=0.2,de;q=0.7")).toBe("de");
  });
});
