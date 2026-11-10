// Records the walkthrough GIFs in docs/walkthroughs as PNG frames, against a running stack.
//
//   node scripts/record-walkthroughs.mjs <frames-dir> [name ...]
//   uv run --with pillow ../../scripts/walkthrough-gifs.py <frames-dir> ../../docs/walkthroughs
//
// Uses the sessions saved by the e2e setup (e2e/.auth). Read-only: forms are filled in to show
// them, but nothing is saved, created or published. Steps on what an install does not have
// are skipped.
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
const main = (page) => page.locator("main");

/** Steps on what may not exist on every install are skipped, not failed. */
async function maybe(target, action) {
  if ((await target.count()) && (await target.first().isVisible())) await action(target.first());
}

/** A page with its caption, scrolled through. */
async function tour(r, route, caption, { scroll = 0, ms = 2000 } = {}) {
  await r.go(route, 300);
  await r.caption(caption, ms);
  if (scroll) await r.scroll(scroll, 10, 1400);
}

/** Point at a section heading of the page, with its caption. */
async function section(r, heading, caption, ms = 1800) {
  r.text = caption;
  const h = r.page.locator("main h2", { hasText: heading }).first();
  if (await h.count()) await r.point(h, ms);
}

/** Click through the page's tabs or filters, each with its caption. */
async function tabs(r, items, ms = 1500) {
  for (const [name, caption] of items) {
    r.text = caption;
    const re = new RegExp(`^${name}`);
    const m = r.page.locator("main");
    const t = m
      .getByRole("link", { name: re })
      .or(m.getByRole("radio", { name: re }))
      .or(m.getByRole("button", { name: re }))
      .first();
    if ((await t.count()) && (await t.isVisible())) await r.click(t, ms);
  }
}

const botId = (bots, name) => bots.find((b) => b.name === name)?.id ?? bots[0]?.id;

/** 1. A simple chatbot: general chat with a language model, no documents. */
async function simpleChatbot(r, bots) {
  const { page } = r;
  await r.go("/admin/chatbots", 600);
  await r.caption("Chatbots: each with its own models, knowledge and audience", 1800);
  r.text = "New chatbot · Step 1: name, description and welcome message";
  await r.click(
    main(page)
      .getByRole("link", { name: /New chatbot/ })
      .first(),
    900,
  );
  await r.type(field(page, "Name"), "Writing helper");
  await r.type(field(page, "Description"), "Drafts, rewrites and translations");
  await r.type(field(page, "Welcome message"), "Hi! What should we write today?");
  await r.caption("Shown for an existing general chatbot (nothing is created here)", 1600);
  const id = botId(bots, "veyntora-gpt");
  await r.go(`/admin/chatbots/${id}/settings/retrieval`, 300);
  r.text = "Retrieval: turn Answer from documents off for general chat";
  await r.point(page.getByLabel(/^Answer from documents/).first(), 2000);
  await r.go(`/admin/chatbots/${id}/settings/generation`, 300);
  await r.caption("Generation: the model, its instructions and how long answers may be", 2000);
  await r.scroll(500, 8, 1400);
  await r.go(`/admin/chatbots/${id}/settings/chat`, 300);
  await r.caption("Chat features: models people may switch to, thinking, attachments", 2200);
  await r.go(`/admin/chatbots/${id}`, 300);
  await r.caption("Details: name, address and welcome message can change at any time", 2200);
}

/** 2. A chatbot that answers from documents (RAG). */
async function ragChatbot(r, bots) {
  const { page } = r;
  const id = botId(bots, "AI research paper");
  await r.go(`/admin/chatbots/new/knowledge?id=${id}`, 300);
  await r.caption("Step 2 · Knowledge: the sources it answers from, weighed and limited", 1800);
  await maybe(page.getByRole("radio", { name: "Boost ×1.5" }), (t) => r.click(t, 1200));
  await maybe(page.getByRole("radio", { name: "Normal" }), (t) => r.click(t, 600));
  await r.go(`/admin/chatbots/${id}/settings`, 300);
  await r.caption("Ingestion: how documents become passages", 1800);
  await r.go(`/admin/chatbots/${id}/settings/retrieval`, 300);
  await r.caption("Retrieval: hybrid search over the passages people may read", 1800);
  await r.go(`/admin/chatbots/${id}/settings/rerank`, 300);
  await r.caption("Reranking: a second model keeps only the passages that fit", 1800);
  await r.go(`/admin/chatbots/${id}/settings/generation`, 300);
  await r.caption(
    "Generation: citations required; ungrounded answers are held back or flagged",
    2000,
  );
  await r.scroll(600, 8, 1200);
  await r.go(`/admin/chatbots/${id}/settings/guardrails`, 300);
  await r.caption("Guardrails: personal data, prompt injection and groundedness checks", 2000);
  await r.go("/admin/playground", 300);
  await r.caption("Playground: try the draft against the live version before publishing", 2200);
}

/** 3. A chatbot with tools: agent mode, MCP tools, web search and code. */
async function toolsChatbot(r, bots) {
  const { page } = r;
  const id = botId(bots, "AI research paper");
  await r.go(`/admin/chatbots/${id}/settings/agent`, 300);
  await r.caption("Agent: the model plans, searches and calls tools within limits", 2000);
  await r.scroll(500, 8, 1400);
  await r.go(`/admin/chatbots/${id}/settings/router`, 300);
  await r.caption("Router: Fast, Agent, or Auto choosing per question", 2000);
  await r.go(`/admin/chatbots/${id}/settings/retrieval`, 300);
  r.text = "Knowledge tools: read-only MCP tools searched with every question";
  await maybe(page.getByText("Knowledge tools", { exact: true }), (t) => r.point(t, 2000));
  await r.go(`/admin/chatbots/${id}/settings/chat`, 300);
  await r.caption("Chat features: web search and the code sandbox, switched on by people", 2200);
  await r.go(`/admin/chatbots/${id}/flow`, 300);
  await r.caption("The pipeline as a flow: every step and where it leads", 2400);
}

/** 4. Automations. */
async function automations(r) {
  const { page } = r;
  await tour(
    r,
    "/admin/automations",
    "Automations: work that runs on a schedule, an event or by hand",
    { ms: 1800 },
  );
  r.text = "Start from a template or from scratch";
  await maybe(main(page).getByRole("link", { name: /New automation/ }), (t) => r.click(t, 1600));
  await r.scroll(400, 8, 1400);
  await r.go("/admin/automations", 300);
  r.text = "Each automation: its trigger, steps on a timeline, safety limits and runs";
  await maybe(
    main(page).locator("a[href^='/admin/automations/']").filter({ hasNotText: /New/ }),
    (t) => r.click(t, 1800),
  );
  await r.scroll(600, 10, 1600);
}

/** 5. Data sources. */
async function dataSources(r) {
  const { page } = r;
  await tour(r, "/admin/sources", "Data sources: everything Veyntora reads, kept in step", {
    ms: 1800,
  });
  r.text = "Connect a source: pick where the documents live";
  await r.click(
    main(page)
      .getByRole("link", { name: /Connect/ })
      .first(),
    1200,
  );
  const kind = (name) => page.getByRole("radio", { name: new RegExp(`^${name}`) });
  await r.click(kind("SharePoint Online"), 600);
  r.text = "SharePoint Online keeps its own permissions";
  await r.type(field(page, "Name"), "Intranet – HR");
  await r.type(field(page, "Tenant (ID or domain)"), "contoso.onmicrosoft.com");
  await r.click(kind("Website"), 600);
  r.text = "Websites: start pages, sitemap, sign-in and JavaScript rendering";
  await r.type(field(page, "Start pages"), "https://intranet.example.com/handbook/");
  await r.scroll(500, 8, 1200);
  r.text = "How documents are read: Auto, fast text, layout or a vision model";
  await r.point(page.getByText("How documents are read", { exact: true }).first(), 1600);
  await r.scroll(500, 8, 1200);
  r.text = "Which files: types, size and paths (not saved in this recording)";
  await r.scroll(500, 8, 1400);
  await r.go("/admin/sources", 300);
  r.text = "Each source: its documents, sync jobs, readers and reading settings";
  await r.click(main(page).locator("table a[href^='/admin/sources/']").first(), 1600);
  await r.scroll(700, 10, 1600);
}

/** 6. Providers and keys. */
async function providers(r) {
  const { page } = r;
  await tour(
    r,
    "/admin/providers",
    "Providers & keys: every model and service, tested and health-checked",
    { ms: 2000 },
  );
  r.text = "Add a provider: choose what it does";
  await r.click(
    main(page)
      .getByRole("link", { name: /Add provider/ })
      .first(),
    1000,
  );
  for (const [kind, text] of [
    [
      "LLM",
      "Language models: self-hosted (vLLM, Ollama) or external (Anthropic, OpenAI-compatible)",
    ],
    ["Embeddings", "Embeddings: turn passages into vectors for search"],
    ["Reranker", "Rerankers: order the passages found by how well they fit"],
    ["Vector store", "Vector store: Qdrant keeps the passages and their permissions"],
    ["Document parser", "Document parsers: Docling or Apache Tika"],
    ["Vision model", "Vision models: read scans, forms and pictures"],
    ["Guardrail", "Guardrails: Llama Guard, Presidio or Azure for safety and personal data"],
    ["Web search", "Web search: SearXNG, Brave or Tavily, for people who switch it on"],
    [
      "Code interpreter",
      "Code interpreter: a sandbox without internet for calculations and charts",
    ],
  ]) {
    r.text = text;
    const radio = page.getByRole("radio", { name: new RegExp(`^${kind}`) }).first();
    if (await radio.count()) await r.click(radio, 1300);
  }
  await r.caption("Keys go straight to OpenBao and are never shown again (not saved here)", 2200);
}

/** 7. Tools (MCP). */
async function tools(r) {
  const { page } = r;
  await tour(r, "/admin/tools", "Tools (MCP): servers whose tools agents may call", { ms: 1800 });
  r.text = "A server's tools: read or write, approval, who may call them";
  await maybe(
    main(page)
      .locator("a[href^='/admin/tools/']")
      .filter({ hasNotText: /New|Add/ }),
    (t) => r.click(t, 1800),
  );
  await r.scroll(600, 10, 1400);
  await r.go("/admin/tools", 300);
  r.text = "Add an MCP server: its address and how it signs in";
  await maybe(main(page).getByRole("link", { name: /(Add|New|Connect)/ }), (t) => r.click(t, 1200));
  await maybe(field(page, "Name"), (t) => r.type(t, "Ticket system"));
  await r.caption("Tools that change data always wait for a person's approval", 2200);
}

/** 8. Channels and the API. */
async function channels(r) {
  await tour(r, "/admin/channels", "Channels & API: where people reach the chatbots", { ms: 1600 });
  await section(
    r,
    "Website widget",
    "Website widget: a chat on your intranet, only on allowed sites",
  );
  await section(r, "Microsoft Teams", "Microsoft Teams: the chatbots in chats and channels");
  await section(r, "Slack", "Slack: the same chatbots in your workspace");
  await section(r, "Where bots can post", "Where automations and bots may post their messages");
  await section(r, "Email", "Email: notifications and reports through your mail server");
  await section(r, "App keys", "App keys: the REST API for your own applications", 2200);
}

/** 10. Knowledge health. */
async function knowledgeHealth(r) {
  await tour(
    r,
    "/admin/knowledge-health",
    "Knowledge health: nightly scans; nothing changes without an owner",
    { ms: 1800 },
  );
  await tabs(r, [
    ["Knowledge gaps", "Knowledge gaps: questions nobody's documents answer"],
    ["Contradictions", "Contradictions: documents that disagree"],
    ["Stale but popular", "Stale but popular: cited often, not updated in months"],
    ["Could not be read", "Could not be read: documents the reader failed on"],
    ["Duplicates", "Duplicates: each finding lists its documents and how to fix them"],
  ]);
  r.text = "Open the document, read it again, or exclude it from answers";
  const doc = r.page.locator("main ul a[href^='/admin/sources/']").first();
  if (await doc.count()) await r.point(doc, 2200);
}

/** 11. Evaluation. */
async function evaluation(r, bots) {
  await tour(r, "/admin/evaluation", "Evaluation: scores by version and a gate before publishing", {
    ms: 1800,
  });
  await tabs(
    r,
    bots.slice(0, 2).map((b) => [b.name, `Scores and runs for ${b.name}`]),
  );
  await section(r, "Publish gate", "Publish gate: a version must pass before it goes live");
  r.text = "Eval sets: test questions, written, imported or generated from documents";
  const sets = r.page.locator("main a[href^='/admin/evaluation/sets']").first();
  if (await sets.count()) {
    await r.click(sets, 1600);
    const set = r.page.locator("main a[href^='/admin/evaluation/sets/']").first();
    if (await set.count()) {
      r.text = "A set's questions with their expected answers and sources";
      await r.click(set, 1600);
      await r.scroll(500, 8, 1400);
    }
  }
}

/** 12. Monitoring. */
async function monitoring(r) {
  await tour(r, "/admin/monitoring", "Monitoring: answers, latency, errors and modes", {
    ms: 1600,
  });
  await tabs(r, [
    ["7 days", "The last 7 days"],
    ["30 days", "The last 30 days"],
    ["AI research paper", "One chatbot at a time"],
  ]);
  await section(r, "Requests per hour", "Requests per hour by mode: Fast, Agent, Auto");
  await section(r, "Alerts", "Alerts: what crossed a threshold");
  await section(r, "Providers", "Providers: health and latency of every model and service");
  await section(r, "Grafana", "Grafana dashboards, linked from here", 2000);
}

/** 13. Integrations. */
async function integrations(r) {
  await tour(r, "/admin/integrations", "Integrations: tracing, dashboards and virus scanning", {
    ms: 1600,
  });
  await section(r, "Langfuse", "Langfuse: every answer's steps, masked, for tracing and cost");
  await section(r, "Grafana", "Grafana: Veyntora's metrics on your own dashboards");
  await section(
    r,
    "Virus scanner",
    "Virus scanner: ClamAV checks every file before it is read",
    2000,
  );
}

/** 14. Infrastructure. */
async function infrastructure(r) {
  await tour(
    r,
    "/admin/infrastructure",
    "Infrastructure: the services Veyntora runs on, and their health",
    { ms: 1800 },
  );
  await section(
    r,
    "Veyntora needs these",
    "Required: PostgreSQL, Valkey, S3, OpenBao, OpenFGA and Keycloak",
  );
  await section(
    r,
    "Set up in the console",
    "Set up in the console: Qdrant, Docling, Tika, the scanner and more",
  );
  await section(r, "Versions", "Versions: every change of settings, with a way back", 2000);
}

/** 15. Usage and budgets. */
async function usage(r) {
  await tour(r, "/admin/usage", "Usage & budgets: tokens and cost, with limits", { ms: 1600 });
  await tabs(r, [
    ["Chatbot", "Spend per chatbot"],
    ["Provider", "Spend per provider and model"],
    ["Group", "Spend per group"],
    ["Cost centre", "Spend per cost centre"],
  ]);
  await section(r, "Budgets", "Budgets: warn, switch to a cheaper model or pause at a limit");
  await section(r, "Limits per user", "Limits per user: questions and agent runs per day", 2000);
}

/** 17. Governance. */
async function governance(r) {
  await tour(r, "/admin/governance", "Governance: data rules, retention, legal holds and GDPR", {
    ms: 1600,
  });
  await section(r, "Policies", "Policies: how long chats, traces and uploads are kept");
  await section(
    r,
    "Data subject requests",
    "Data subject requests: access, deletion and correction, with deadlines",
  );
  await section(
    r,
    "Data rules by chatbot",
    "Data rules: which external providers each chatbot may use",
  );
  await section(r, "Legal holds", "Legal holds: keep what a case needs, past its retention");
  await section(r, "Platform roles", "Platform roles: who may administer which area", 1600);
  r.text = "A request's history, steps and evidence";
  const req = r.page.locator("main a[href^='/admin/governance/gdpr/']").first();
  if (await req.count()) {
    await r.click(req, 1800);
    await r.scroll(400, 8, 1400);
  }
}

/** 18. Audit log. */
async function audit(r) {
  const { page } = r;
  await tour(r, "/admin/audit", "Audit log: every change, hash-chained and archived write-once", {
    ms: 1800,
  });
  r.text = "Filter by category and time";
  const cat = page.getByLabel(/^Category/).first();
  if (await cat.count()) {
    const options = await cat.locator("option").allTextContents();
    if (options[1]) await r.choose(cat, options[1], 1400);
    await r.choose(cat, options[0], 600);
  }
  r.text = "Each entry: who, what, before and after";
  const row = page.locator("main li button, main table tbody tr").nth(1);
  if (await row.count()) await r.click(row, 2000);
  await r.scroll(500, 8, 1400);
}

/** 9. Conversations. */
async function conversations(r) {
  await tour(r, "/admin/conversations", "Conversations: answers to review, with what went wrong", {
    ms: 1800,
  });
  await tabs(r, [
    ["AI research paper", "Filter by chatbot"],
    ["Not helpful", "Answers rated not helpful"],
    ["No answer found", "Questions nothing answered"],
    ["All chatbots", "Every chatbot"],
  ]);
  await section(r, "Question", "The question, the answer and its rating");
  await section(r, "Retrieved sources", "The sources it found, and what may have gone wrong", 2200);
}

/** 16. Users & groups. */
async function users(r) {
  const { page } = r;
  await tour(
    r,
    "/admin/users",
    "Users & groups: access goes to groups; Keycloak stays the source of identities",
    { ms: 2200 },
  );
  const tab = (name) => main(page).getByRole("link", { name, exact: true }).first();
  r.text = "People: who has access, through which groups";
  await maybe(tab("People"), (t) => r.click(t, 1600));
  r.text = "Roles & permissions: who may administer what";
  await maybe(tab("Roles & permissions"), (t) => r.click(t, 1800));
  await r.scroll(500, 8, 1200);
  r.text = "Access reviews: owners confirm who still needs access";
  await maybe(tab("Access reviews"), (t) => r.click(t, 1800));
  await r.click(nav(page, "Users & groups"), 300);
  r.text = "A new group: a list of people, or everyone matching a rule (not saved)";
  await maybe(page.getByRole("link", { name: /New group/ }), (t) => r.click(t, 1000));
  await maybe(field(page, "Group name"), (t) => r.type(t, "Finance pilot"));
  await maybe(field(page, "Description"), (t) =>
    r.type(t, "Early users of the finance assistant", 1400),
  );
}

/** The chat for employees. */
async function chat(r) {
  const { page } = r;
  await r.go("/home", 600);
  await r.caption("Home: choose an assistant and ask a question", 1600);
  await r.type(page.getByRole("textbox").first(), "What does the ReAct paper propose?", 1200);
  r.text = "Answers come only from documents you may read, with numbered sources";
  const thread = page.locator('a[href^="/chat/"]').first();
  if (await thread.count()) {
    await r.click(thread, 800);
    await r.scroll(-3000, 4, 600);
    await r.scroll(700, 10, 1600);
  }
  for (const [link, text] of [
    ["Chats & knowledge", "Chats & knowledge: past chats, saved answers and your own files"],
    ["Notifications", "Notifications: approvals, expert replies and reports, by day"],
    ["Settings", "Settings: language, answer length, notifications and privacy"],
  ]) {
    await r.click(nav(page, link), 0);
    await r.caption(text, 2000);
  }
}

/** The admin console at a glance. */
async function adminConsole(r) {
  const { page } = r;
  await r.go("/admin", 600);
  await r.caption("Admin console: health, usage and what needs attention", 2200);
  await r.scroll(500, 8, 1200);
  r.text = "Areas grouped by what you do: build, knowledge, connections, operate, govern";
  await r.point(page.getByRole("navigation", { name: "Admin" }).first(), 2200);
  await r.click(page.getByRole("button", { name: "Collapse sidebar" }), 1400);
  await r.click(page.getByRole("button", { name: /Expand sidebar/ }), 1200);
}

const REELS = {
  "01-simple-chatbot": { user: "admin", run: simpleChatbot },
  "02-rag-chatbot": { user: "admin", run: ragChatbot },
  "03-tools-chatbot": { user: "admin", run: toolsChatbot },
  "04-automations": { user: "admin", run: automations },
  "05-data-sources": { user: "admin", run: dataSources },
  "06-providers": { user: "admin", run: providers },
  "07-tools-mcp": { user: "admin", run: tools },
  "08-channels-api": { user: "admin", run: channels },
  "09-conversations": { user: "admin", run: conversations },
  "10-knowledge-health": { user: "admin", run: knowledgeHealth },
  "11-evaluation": { user: "admin", run: evaluation },
  "12-monitoring": { user: "admin", run: monitoring },
  "13-integrations": { user: "admin", run: integrations },
  "14-infrastructure": { user: "admin", run: infrastructure },
  "15-usage-budgets": { user: "admin", run: usage },
  "16-users-groups": { user: "admin", run: users },
  "17-governance": { user: "admin", run: governance },
  "18-audit-log": { user: "admin", run: audit },
  chat: { user: "admin", run: chat },
  "admin-console": { user: "admin", run: adminConsole },
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
    const bots = await (await page.request.get(`${BASE}/api/v1/admin/chatbots/cards`)).json();
    const r = new Reel(page);
    try {
      await reel.run(r, bots);
    } catch (e) {
      console.error(`${name}: ${String(e).split("\n")[0]}`);
    }
    await r.save(path.join(out, name));
    console.log(`${name}: ${r.frames.length} frames`);
    await context.close();
  }
} finally {
  await browser.close();
}
