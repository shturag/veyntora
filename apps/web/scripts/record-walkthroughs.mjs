// Records the walkthrough GIFs in docs/walkthroughs as PNG frames, against a running stack.
//
//   node scripts/record-walkthroughs.mjs <frames-dir> [name ...]
//   uv run --with pillow ../../scripts/walkthrough-gifs.py <frames-dir> ../../docs/walkthroughs
//
// Uses the sessions saved by the e2e setup (e2e/.auth); WALKTHROUGH_BOT names the chatbot whose
// wizard steps are shown (default: the first). Read-only: forms are filled in to show
// them, but nothing is saved, created or published.
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { chromium } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const VIEWPORT = { width: 1280, height: 800 };

const CURSOR = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="26" viewBox="0 0 22 26"><path d="M2 2v19l5-5 3.5 8 3-1.3-3.5-7.7h7z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

/** One walkthrough: a page with a drawn cursor, captured frame by frame; each frame keeps its caption. */
class Reel {
  constructor(page) {
    this.page = page;
    this.frames = [];
    this.x = VIEWPORT.width / 2;
    this.y = VIEWPORT.height / 2;
    this.text = "";
    this.pressed = false;
  }

  async overlay() {
    await this.page.evaluate(
      ([x, y, pressed, cursor]) => {
        let c = document.getElementById("wt-cursor");
        if (!c) {
          c = document.createElement("div");
          c.id = "wt-cursor";
          c.innerHTML = cursor;
          c.style.cssText =
            "position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:26px;";
          document.body.append(c);
        }
        c.style.left = `${x - 2}px`;
        c.style.top = `${y - 2}px`;
        let r = document.getElementById("wt-ring");
        if (!r) {
          r = document.createElement("div");
          r.id = "wt-ring";
          r.style.cssText =
            "position:fixed;z-index:2147483646;pointer-events:none;width:34px;height:34px;border-radius:50%;background:rgba(91,61,245,.28);border:2px solid rgba(91,61,245,.7);";
          document.body.append(r);
        }
        r.style.left = `${x - 17}px`;
        r.style.top = `${y - 17}px`;
        r.style.display = pressed ? "block" : "none";
      },
      [this.x, this.y, this.pressed, CURSOR],
    );
  }

  async shot(ms = 80) {
    await this.overlay();
    this.frames.push({ png: await this.page.screenshot(), ms, caption: this.text });
  }

  async caption(text, ms = 1400) {
    this.text = text;
    await this.shot(ms);
  }

  async settle() {
    await this.page.waitForLoadState("networkidle").catch(() => {});
    await this.page.waitForTimeout(300);
  }

  async go(route, ms = 1200) {
    await this.page.goto(BASE + route);
    await this.settle();
    await this.shot(ms);
  }

  async move(target) {
    await target.scrollIntoViewIfNeeded();
    const box = await target.boundingBox();
    if (!box) throw new Error(`not visible: ${target}`);
    const [x0, y0] = [this.x, this.y];
    const [x1, y1] = [box.x + Math.min(box.width / 2, 120), box.y + box.height / 2];
    const steps = Math.max(4, Math.min(12, Math.round(Math.hypot(x1 - x0, y1 - y0) / 60)));
    for (let i = 1; i <= steps; i++) {
      const k = i / steps;
      const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
      this.x = x0 + (x1 - x0) * e;
      this.y = y0 + (y1 - y0) * e;
      await this.page.mouse.move(this.x, this.y);
      await this.shot(35);
    }
  }

  async point(target, ms = 900) {
    await this.move(target);
    await this.shot(ms);
  }

  async click(target, ms = 900) {
    await this.move(target);
    this.pressed = true;
    await this.shot(160);
    await target.click();
    this.pressed = false;
    await this.settle();
    await this.shot(ms);
  }

  async type(target, text, ms = 500) {
    await this.click(target, 120);
    for (let i = 0; i < text.length; i += 3) {
      await target.pressSequentially(text.slice(i, i + 3));
      await this.shot(55);
    }
    await this.shot(ms);
  }

  async choose(target, label, ms = 800) {
    await this.move(target);
    await target.selectOption({ label });
    await this.shot(ms);
  }

  async scroll(dy, steps = 8, ms = 900) {
    for (let i = 0; i < steps; i++) {
      await this.page.mouse.wheel(0, dy / steps);
      await this.page.waitForTimeout(60);
      await this.shot(60);
    }
    await this.shot(ms);
  }

  async save(dir) {
    await rm(dir, { recursive: true, force: true });
    await mkdir(dir, { recursive: true });
    const index = [];
    for (const [i, f] of this.frames.entries()) {
      const name = `${String(i).padStart(4, "0")}.png`;
      await writeFile(path.join(dir, name), f.png);
      index.push({ file: name, ms: f.ms, caption: f.caption });
    }
    await writeFile(path.join(dir, "frames.json"), JSON.stringify(index));
  }
}

const nav = (page, name) =>
  page.getByRole("navigation").getByRole("link", { name, exact: true }).first();
const field = (page, label) =>
  page
    .locator("main")
    .getByLabel(new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`))
    .first();

/** The admin console: what each area is for. */
async function adminConsole(r) {
  const { page } = r;
  await r.go("/admin", 600);
  await r.caption("Admin console: health, usage and what needs attention", 2200);
  await r.scroll(500, 8, 1200);
  for (const [link, text] of [
    ["Chatbots", "Chatbots: each with its own knowledge, models and audience"],
    ["Pipelines", "Pipelines: how every chatbot searches and answers"],
    ["Data sources", "Data sources: everything Veyntora reads, kept in step"],
    ["Providers & keys", "Providers: language models, embeddings, rerankers, vector store, parser"],
    ["Tools (MCP)", "Tools: MCP servers that agents may call, with approval for writes"],
    ["Knowledge health", "Knowledge health: stale, duplicate and unanswered topics"],
    ["Evaluation", "Evaluation: test questions that gate publishing"],
    ["Monitoring", "Monitoring: answers, latency and errors"],
    ["Usage & budgets", "Usage and budgets per chatbot, team and model"],
    ["Governance", "Governance: data rules, PII, retention and GDPR requests"],
    ["Audit log", "Audit log: every change, tamper-evident"],
  ]) {
    await r.click(nav(page, link), 0);
    await r.caption(text, 2000);
  }
  r.text = "Drag the edge to resize the sidebar, or fold it into a rail";
  const handle = page.getByRole("separator", { name: "Resize the sidebar" });
  await r.move(handle);
  r.pressed = true;
  await page.mouse.down();
  for (const dx of [20, 40, 60, 80, 60, 30, 0]) {
    r.x = 240 + dx;
    await page.mouse.move(r.x, r.y);
    await r.shot(70);
  }
  await page.mouse.up();
  r.pressed = false;
  await r.click(page.getByRole("button", { name: "Collapse sidebar" }), 1600);
  await r.click(page.getByRole("button", { name: /Expand sidebar/ }), 1200);
}

/** Connecting a data source: pick the system, fill in the connection, choose readers. */
async function connectSource(r) {
  const { page } = r;
  await r.go("/admin/sources", 600);
  await r.caption("Data sources: sync status and documents at a glance", 2000);
  r.text = "Connect a new source";
  await r.click(
    page
      .locator("main")
      .getByRole("link", { name: /Connect/ })
      .first(),
    1200,
  );
  await r.caption("Pick where the documents live: files, pages or tickets", 1800);
  const kind = (name) => page.getByRole("radio", { name: new RegExp(`^${name}`) });
  await r.click(kind("SharePoint Online"), 1000);
  r.text = "SharePoint Online keeps its own permissions";
  await r.type(field(page, "Name"), "Intranet – HR");
  await r.type(field(page, "Tenant (ID or domain)"), "contoso.onmicrosoft.com");
  await r.type(field(page, "Application (client) ID"), "5f1c2e7a-0b9d-4c51-9a3e-8d27c0f4b6a1");
  await r.type(field(page, "Site address"), "https://contoso.sharepoint.com/sites/hr");
  r.text = "Map SharePoint groups to Veyntora groups, choose a schedule";
  await r.scroll(420, 8, 600);
  await r.choose(page.getByLabel("Sync schedule (UTC)"), "Every 4 hours", 1400);
  await r.caption("Secrets are write-only: stored in OpenBao, never shown again", 2000);
  await r.scroll(-900, 8, 400);
  r.text = "Other systems work the same way";
  await r.click(kind("Git \\(GitHub, GitLab\\)"), 600);
  await r.type(field(page, "Repositories (one per line)"), "acme/handbook");
  await r.click(kind("Jira"), 600);
  await r.type(field(page, "Project keys (one per line)"), "SUP");
  await r.scroll(380, 6, 400);
  await r.click(page.getByLabel(/^Include comments/), 1000);
  r.text = "Choose who may read, then connect (not saved in this recording)";
  await r.click(page.getByLabel(/^all-employees/).first(), 600);
  await r.point(
    page
      .locator("main")
      .getByRole("button", { name: /^(Connect|Create)/ })
      .last(),
    2000,
  );
  await r.go("/admin/sources", 300);
  r.text = "Each source shows its documents, sync jobs and readers";
  const first = page.locator("main table a[href^='/admin/sources/']").first();
  await r.click(first, 1600);
  const list = page.getByRole("region", { name: "Document list" });
  if (await list.count()) {
    await r.point(list, 400);
    await r.scroll(500, 8, 1400);
  }
}

/** Creating a chatbot: the five wizard steps. */
async function createChatbot(r, bot) {
  const { page } = r;
  await r.go("/admin/chatbots", 600);
  await r.caption("Chatbots: who uses them, which version is live", 1800);
  r.text = "Create a chatbot";
  await r.click(
    page
      .locator("main")
      .getByRole("link", { name: /New chatbot/ })
      .first(),
    1000,
  );
  r.text = "Step 1 · Basics: name, welcome message, answer language";
  await r.type(field(page, "Name"), "HR assistant");
  await r.type(field(page, "Description"), "Leave, payroll and benefits");
  await r.type(field(page, "Welcome message"), "Hi! Ask me about leave, payroll or benefits.");
  await r.choose(field(page, "Answer language"), "Same as the question", 1600);
  await r.caption("Steps 2 to 5, shown for an existing chatbot", 1600);
  await r.go(`/admin/chatbots/new/knowledge?id=${bot}`, 300);
  await r.caption("Step 2 · Knowledge: attach sources, limit folders, weigh them", 1200);
  await r.click(page.getByRole("radio", { name: "Boost ×1.5" }).first(), 1400);
  await r.click(page.getByRole("radio", { name: "Normal" }).first(), 800);
  await r.go(`/admin/chatbots/new/pipeline?id=${bot}`, 300);
  await r.caption("Step 3 · Pipeline: documents or general chat, models, behaviour", 1600);
  await r.scroll(700, 10, 1400);
  await r.scroll(700, 10, 1400);
  await r.go(`/admin/chatbots/new/access?id=${bot}`, 300);
  await r.caption("Step 4 · Access: who may chat, approve, edit or administer", 2400);
  await r.go(`/admin/chatbots/new/publish?id=${bot}`, 300);
  await r.caption(
    "Step 5 · Test & publish: a summary of every step, checks before going live",
    1800,
  );
  r.text = "Test in the Playground first; every version can be rolled back";
  await r.point(page.getByRole("link", { name: /Test/ }).first(), 1400);
  await r.point(page.locator("aside").getByRole("button").first(), 2000);
}

/** The chat for employees: ask, read the answer, check the sources. */
async function chat(r) {
  const { page } = r;
  await r.go("/home", 600);
  await r.caption("Home: choose an assistant and ask a question", 1600);
  const box = page.getByRole("textbox").first();
  await r.type(box, "What is the AGENTS framework for language agents?", 1200);
  r.text = "Answers come only from documents you may read, with numbered sources";
  // An existing conversation with sources (recording never sends a question).
  const named = page.locator('a[href^="/chat/"]', { hasText: "Open-source Framework" }).first();
  const thread = (await named.count()) ? named : page.locator('a[href^="/chat/"]').first();
  if (!(await thread.count())) throw new Error("chat: needs an existing conversation with sources");
  await r.click(thread, 600);
  await r.move(page.locator("main p").first());
  await r.scroll(-3000, 6, 1200);
  await r.scroll(600, 10, 900);
  await r.scroll(600, 10, 1200);
  r.text = "Each source shows the passage it came from and opens the document";
  await r.point(page.getByRole("link", { name: "Open document" }).first(), 2000);
  r.text = "Rate, save or copy an answer; regenerate it";
  await r.point(page.getByRole("button", { name: /Regenerate/ }).last(), 1600);
  r.text = "Fast for document answers, Agent for tasks, Auto picks for you";
  await r.point(page.getByRole("radio", { name: "Agent" }).first(), 1800);
  for (const [link, text] of [
    ["Chats & knowledge", "Chats & knowledge: past chats and saved answers"],
    ["Approvals", "Approvals: actions an agent wants to carry out wait for you"],
    ["Settings", "Settings: language, notifications, connected accounts, privacy"],
  ]) {
    await r.click(nav(page, link), 0);
    await r.caption(text, 2000);
  }
}

/** Users, groups, roles and access reviews. */
async function userManagement(r) {
  const { page } = r;
  await r.go("/admin/users", 600);
  await r.caption(
    "Users & groups: access is given to groups; Keycloak stays the source of identities",
    2400,
  );
  const tab = (name) => page.locator("main").getByRole("link", { name, exact: true }).first();
  r.text = "People: who has access, through which groups";
  await r.click(tab("People"), 1600);
  const person = page
    .locator("main tr", { hasText: "@" })
    .locator("a[href^='/admin/users/']")
    .first();
  if (await person.count()) {
    r.text = "A person's groups, chatbots and roles in one place";
    await r.click(person, 2200);
    await page.goBack();
    await r.settle();
  }
  r.text = "Roles & permissions: who may administer what";
  await r.click(tab("Roles & permissions"), 2000);
  await r.scroll(500, 8, 1200);
  r.text = "Access reviews: owners confirm who still needs access";
  await r.click(tab("Access reviews"), 2000);
  await r.click(nav(page, "Users & groups"), 400);
  r.text = "Groups from Keycloak, rules on attributes, or lists of people";
  await r.click(page.getByRole("link", { name: /New group/ }).first(), 1000);
  await r.type(field(page, "Group name"), "Finance pilot");
  await r.type(field(page, "Description"), "Early users of the finance assistant");
  await r.click(page.getByLabel(/^A list of people/), 600);
  await r.type(field(page, "Add a person"), "emp", 1600);
  r.text = "Memberships can end on a date (not saved in this recording)";
  await r.point(field(page, "Memberships end (optional)"), 2200);
}

const REELS = {
  "admin-console": { user: "admin", run: adminConsole },
  "connect-data-source": { user: "admin", run: connectSource },
  "create-chatbot": { user: "admin", run: createChatbot },
  chat: { user: "admin", run: chat },
  "user-management": { user: "admin", run: userManagement },
};

const [out, ...only] = process.argv.slice(2);
if (!out) throw new Error("usage: record-walkthroughs.mjs <frames-dir> [name ...]");
const browser = await chromium.launch();
try {
  for (const [name, reel] of Object.entries(REELS)) {
    if (only.length && !only.includes(name)) continue;
    const context = await browser.newContext({
      storageState: `e2e/.auth/${reel.user}.json`,
      viewport: VIEWPORT,
      locale: "en-GB",
      colorScheme: "light",
    });
    const page = await context.newPage();
    const bots = await (await page.request.get(`${BASE}/api/v1/admin/chatbots`)).json();
    const r = new Reel(page);
    const bot = bots.find((b) => b.name === process.env.WALKTHROUGH_BOT) ?? bots[0];
    await reel.run(r, bot?.id);
    await r.save(path.join(out, name));
    console.log(`${name}: ${r.frames.length} frames`);
    await context.close();
  }
} finally {
  await browser.close();
}
