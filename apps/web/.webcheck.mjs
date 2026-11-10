// Whole-app check (read-only): every page in Chromium, Firefox and WebKit at several sizes,
// in English and German. Records console errors, failed requests, sideways scrolling,
// missing texts, accessibility violations and load times. Temporary; not committed.
import AxeBuilder from "@axe-core/playwright";
import { chromium, firefox, webkit } from "@playwright/test";
import { writeFileSync } from "node:fs";

const BASE = "http://localhost:3000";
const STATE = "e2e/.auth/admin.json";
const OUT = process.argv[2];
const SKIP = /sign-out|\/api\/|[?&]q=|logout|download|\.(pdf|csv|json|zip)$/i;

async function crawl() {
  const b = await chromium.launch();
  const c = await b.newContext({ baseURL: BASE, storageState: STATE, viewport: { width: 1600, height: 1000 } });
  const p = await c.newPage();
  const seen = new Set(["/home", "/admin", "/library", "/settings", "/help", "/status", "/approvals", "/handoff", "/notifications"]);
  const queue = [...seen];
  while (queue.length && seen.size < 140) {
    const path = queue.shift();
    try {
      await p.goto(path, { waitUntil: "domcontentloaded", timeout: 20000 });
      const hrefs = await p.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
      for (const h of hrefs) {
        if (!h || !h.startsWith("/") || h.startsWith("//") || SKIP.test(h)) continue;
        const clean = h.split("#")[0];
        // One page per route shape and id: drop list filters and paging.
        const key = clean.replace(/\?(page|limit|cursor|status|q|bot|tab|day)=[^&]*/g, "");
        if (!seen.has(key)) {
          seen.add(key);
          queue.push(key);
        }
      }
    } catch {}
  }
  await b.close();
  return [...seen];
}

async function check(engine, name, width, pages, locale, opts = {}) {
  const b = await engine.launch();
  const c = await b.newContext({ baseURL: BASE, storageState: STATE, viewport: { width, height: 900 } });
  await c.addCookies([{ name: "vey_locale", value: locale, url: BASE }]);
  const out = [];
  for (const path of pages) {
    const p = await c.newPage();
    const errors = [];
    const failed = [];
    p.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 200)));
    p.on("pageerror", (e) => errors.push("pageerror: " + String(e).slice(0, 200)));
    p.on("response", (r) => r.status() >= 500 && failed.push(`${r.status()} ${r.url().replace(BASE, "")}`));
    const row = { browser: name, width, locale, path };
    try {
      const t0 = Date.now();
      const res = await p.goto(path, { waitUntil: "networkidle", timeout: 30000 });
      row.status = res?.status();
      row.ms = Date.now() - t0;
      const info = await p.evaluate(() => {
        const nav = performance.getEntriesByType("navigation")[0];
        const bytes = performance.getEntriesByType("resource").reduce((s, r) => s + (r.transferSize || 0), 0) + (nav?.transferSize || 0);
        const text = document.body.innerText;
        // next-intl shows a missing text as its key, e.g. "sources.reading.title".
        const keys = [...new Set(text.match(/\b[a-z][a-zA-Z]+\.[a-z][a-zA-Z]+\.[a-zA-Z.]+\b/g) || [])].filter((k) => !/^(e\.g|i\.e|www|veyntora\.local)/.test(k) && !k.includes("@"));
        const wide = document.documentElement.scrollWidth > window.innerWidth + 1;
        const culprits = wide ? [...document.querySelectorAll("body *")].filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1 && getComputedStyle(el).position !== "fixed").slice(0, 3).map((el) => el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.split(" ").slice(0, 2).join(".") : "")) : [];
        return { load: Math.round(nav?.duration || 0), kb: Math.round(bytes / 1024), keys, wide, culprits };
      });
      Object.assign(row, info);
      if (opts.axe) {
        const a = await new AxeBuilder({ page: p }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
        row.axe = a.violations.map((v) => `${v.id}(${v.nodes.length})`);
      }
    } catch (e) {
      row.error = String(e).split("\n")[0].slice(0, 160);
    }
    row.errors = errors;
    row.failed = failed;
    out.push(row);
    await p.close();
  }
  await b.close();
  return out;
}

const pages = await crawl();
console.log("pages", pages.length);
const runs = [
  [chromium, "chromium", 1600, "en", { axe: true }],
  [chromium, "chromium", 1280, "de", {}],
  [chromium, "chromium", 768, "en", {}],
  [chromium, "chromium", 390, "en", {}],
  [chromium, "chromium", 390, "de", {}],
  [firefox, "firefox", 1440, "en", {}],
  [firefox, "firefox", 390, "en", {}],
  [webkit, "webkit", 1440, "en", {}],
  [webkit, "webkit", 390, "en", {}],
];
const all = [];
for (const [engine, name, width, locale, opts] of runs) {
  const rows = await check(engine, name, width, pages, locale, opts);
  all.push(...rows);
  const bad = rows.filter((r) => r.error || r.errors.length || r.failed.length || r.wide || r.keys?.length || r.axe?.length || (r.status && r.status >= 400));
  console.log(`${name} ${width} ${locale}: ${rows.length} pages, ${bad.length} with findings`);
}
writeFileSync(OUT, JSON.stringify({ pages, rows: all }, null, 1));
