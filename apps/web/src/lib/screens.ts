/**
 * Every screen of design/prototype mapped to its route.
 *
 * This is the single source for navigation guards, Phase 0 placeholders and the Playwright
 * route sweep. `file` is the prototype file; `phase` is the delivery phase that builds the
 * screen (0 means built now). Titles and summaries live in messages/{en,de}.json under
 * `screens.<key>`.
 */

export type Shell = "public" | "user" | "admin" | "wizard";

export type AdminArea =
  | "overview"
  | "chatbots"
  | "automations"
  | "pipelines"
  | "playground"
  | "sources"
  | "providers"
  | "tools"
  | "channels"
  | "conversations"
  | "knowledge_health"
  | "evaluation"
  | "monitoring"
  | "usage"
  | "users"
  | "governance"
  | "audit";

export type Screen = {
  key: string;
  file: string;
  /** Next.js route pattern. */
  route: string;
  shell: Shell;
  phase: number;
  area?: AdminArea;
  /** For screens that are states of another route rather than their own page. */
  stateOf?: string;
  /** Built with real data (no longer a phase placeholder); covered by its own e2e tests. */
  built?: true;
};

export const SAMPLE_ID = "00000000-0000-0000-0000-000000000000";

export const SCREENS: readonly Screen[] = [
  // public
  { key: "landing", file: "index.html", route: "/", shell: "public", phase: 0 },
  { key: "signIn", file: "SignIn.html", route: "/sign-in", shell: "public", phase: 0 },
  { key: "status", file: "Status.html", route: "/status", shell: "public", phase: 0 },
  { key: "help", file: "Help.html", route: "/help", shell: "public", phase: 1, built: true },

  // user app
  { key: "home", file: "Home.html", route: "/home", shell: "user", phase: 1, built: true },
  { key: "chat", file: "Main.html", route: "/chat/[id]", shell: "user", phase: 1, built: true },
  {
    key: "chatFast",
    file: "ChatFast.html",
    route: "/chat/[id]",
    shell: "user",
    phase: 1,
    stateOf: "chat",
  },
  {
    key: "agentRunning",
    file: "AgentRunning.html",
    route: "/chat/[id]",
    shell: "user",
    phase: 3,
    stateOf: "chat",
  },
  {
    key: "chatStates",
    file: "ChatStates.html",
    route: "/chat/[id]",
    shell: "user",
    phase: 1,
    stateOf: "chat",
  },
  {
    key: "mobile",
    file: "Mobile.html",
    route: "/chat/[id]",
    shell: "user",
    phase: 1,
    stateOf: "chat",
  },
  {
    key: "source",
    file: "Source.html",
    route: "/source/[id]",
    shell: "user",
    phase: 1,
    built: true,
  },
  { key: "library", file: "Library.html", route: "/library", shell: "user", phase: 1, built: true },
  { key: "savedAnswers", file: "SavedAnswers.html", route: "/saved", shell: "user", phase: 5, built: true },
  {
    key: "approvals",
    file: "Approvals.html",
    route: "/approvals",
    shell: "user",
    phase: 3,
    built: true,
  },
  { key: "handoff", file: "Handoff.html", route: "/handoff", shell: "user", phase: 5, built: true },
  {
    key: "settings",
    file: "Settings.html",
    route: "/settings",
    shell: "user",
    phase: 2,
    built: true,
  },

  // admin: overview and chatbots
  {
    key: "overview",
    file: "Overview.html",
    route: "/admin",
    shell: "admin",
    phase: 6,
    area: "overview",
  },
  {
    key: "bots",
    file: "Bots.html",
    route: "/admin/chatbots",
    shell: "admin",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botOverview",
    file: "BotOverview.html",
    route: "/admin/chatbots/[id]",
    shell: "admin",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botFlow",
    file: "BotFlow.html",
    route: "/admin/chatbots/[id]/flow",
    shell: "admin",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botKnowledge",
    file: "BotKnowledge.html",
    route: "/admin/chatbots/[id]/knowledge",
    shell: "admin",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botAccess",
    file: "BotAccess.html",
    route: "/admin/chatbots/[id]/access",
    shell: "admin",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "versions",
    file: "Versions.html",
    route: "/admin/chatbots/[id]/versions",
    shell: "admin",
    phase: 6,
    built: true,
    area: "chatbots",
  },

  // admin: new chatbot wizard
  {
    key: "botCreate",
    file: "BotCreate.html",
    route: "/admin/chatbots/new",
    shell: "wizard",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botCreateKnowledge",
    file: "BotCreateKnowledge.html",
    route: "/admin/chatbots/new/knowledge",
    shell: "wizard",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botCreatePipeline",
    file: "BotCreatePipeline.html",
    route: "/admin/chatbots/new/pipeline",
    shell: "wizard",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botCreateAccess",
    file: "BotCreateAccess.html",
    route: "/admin/chatbots/new/access",
    shell: "wizard",
    phase: 4,
    built: true,
    area: "chatbots",
  },
  {
    key: "botCreatePublish",
    file: "BotCreatePublish.html",
    route: "/admin/chatbots/new/publish",
    shell: "wizard",
    phase: 4,
    built: true,
    area: "chatbots",
  },

  // admin: pipelines (per chatbot)
  {
    key: "pipeline",
    file: "Pipeline.html",
    route: "/admin/pipelines/[botId]",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "pipelineIngestion",
    file: "PipelineIngestion.html",
    route: "/admin/pipelines/[botId]/ingestion",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "pipelineRerank",
    file: "PipelineRerank.html",
    route: "/admin/pipelines/[botId]/rerank",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "pipelineGeneration",
    file: "PipelineGeneration.html",
    route: "/admin/pipelines/[botId]/generation",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "pipelineAgent",
    file: "PipelineAgent.html",
    route: "/admin/pipelines/[botId]/agent",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "pipelineRouter",
    file: "PipelineRouter.html",
    route: "/admin/pipelines/[botId]/router",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "pipelineGuardrails",
    file: "PipelineGuardrails.html",
    route: "/admin/pipelines/[botId]/guardrails",
    shell: "admin",
    phase: 2,
    area: "pipelines",
    built: true,
  },
  {
    key: "playground",
    file: "Playground.html",
    route: "/admin/playground",
    shell: "admin",
    phase: 2,
    area: "playground",
    built: true,
  },

  // admin: data, providers, tools, channels
  {
    key: "dataSources",
    file: "DataSources.html",
    route: "/admin/sources",
    shell: "admin",
    phase: 1,
    area: "sources",
    built: true,
  },
  {
    key: "connectSource",
    file: "ConnectSource.html",
    route: "/admin/sources/new",
    shell: "admin",
    phase: 1,
    area: "sources",
    built: true,
  },
  {
    key: "sourceDetail",
    file: "SourceDetail.html",
    route: "/admin/sources/[id]",
    shell: "admin",
    phase: 1,
    area: "sources",
    built: true,
  },
  {
    key: "providers",
    file: "Providers.html",
    route: "/admin/providers",
    shell: "admin",
    phase: 2,
    area: "providers",
    built: true,
  },
  {
    key: "addProvider",
    file: "AddProvider.html",
    route: "/admin/providers/new",
    shell: "admin",
    phase: 2,
    area: "providers",
    built: true,
  },
  {
    key: "mcpServers",
    file: "MCPServers.html",
    route: "/admin/tools",
    shell: "admin",
    phase: 3,
    built: true,
    area: "tools",
  },
  {
    key: "mcpRegister",
    file: "MCPRegister.html",
    route: "/admin/tools/new",
    shell: "admin",
    phase: 3,
    built: true,
    area: "tools",
  },
  {
    key: "mcpServerDetail",
    file: "MCPServerDetail.html",
    route: "/admin/tools/[id]",
    shell: "admin",
    phase: 3,
    built: true,
    area: "tools",
  },
  {
    key: "channels",
    file: "Channels.html",
    route: "/admin/channels",
    shell: "admin",
    phase: 4,
    built: true,
    area: "channels",
  },

  // admin: automations
  {
    key: "automations",
    file: "Automations.html",
    route: "/admin/automations",
    shell: "admin",
    phase: 5,
    built: true,
    area: "automations",
  },
  {
    key: "automationNew",
    file: "AutomationNew.html",
    route: "/admin/automations/new",
    shell: "admin",
    phase: 5,
    built: true,
    area: "automations",
  },
  {
    key: "automationBuilder",
    file: "AutomationBuilder.html",
    route: "/admin/automations/[id]",
    shell: "admin",
    phase: 5,
    built: true,
    area: "automations",
  },
  {
    key: "automationTrigger",
    file: "AutomationTrigger.html",
    route: "/admin/automations/[id]/trigger",
    shell: "admin",
    phase: 5,
    built: true,
    area: "automations",
  },
  {
    key: "automationAgentStep",
    file: "AutomationAgentStep.html",
    route: "/admin/automations/[id]/agent-step/[stepId]",
    shell: "admin",
    phase: 5,
    built: true,
    area: "automations",
  },
  {
    key: "automationApprovalStep",
    file: "AutomationApprovalStep.html",
    route: "/admin/automations/[id]/approval-step/[stepId]",
    shell: "admin",
    phase: 5,
    built: true,
    area: "automations",
  },
  {
    key: "runTrace",
    file: "RunTrace.html",
    route: "/admin/runs/[id]",
    shell: "admin",
    phase: 3,
    built: true,
    area: "automations",
  },

  // admin: operate
  {
    key: "conversations",
    file: "Conversations.html",
    route: "/admin/conversations",
    shell: "admin",
    phase: 6,
    area: "conversations",
  },
  {
    key: "knowledgeHealth",
    file: "KnowledgeHealth.html",
    route: "/admin/knowledge-health",
    shell: "admin",
    phase: 5,
    built: true,
    area: "knowledge_health",
  },
  {
    key: "evaluation",
    file: "Evaluation.html",
    route: "/admin/evaluation",
    shell: "admin",
    phase: 6,
    built: true,
    area: "evaluation",
  },
  {
    key: "evalSets",
    file: "EvalSets.html",
    route: "/admin/evaluation/sets",
    shell: "admin",
    phase: 6,
    built: true,
    area: "evaluation",
  },
  {
    key: "monitoring",
    file: "Monitoring.html",
    route: "/admin/monitoring",
    shell: "admin",
    phase: 6,
    area: "monitoring",
  },
  {
    key: "usage",
    file: "Usage.html",
    route: "/admin/usage",
    shell: "admin",
    phase: 6,
    built: true,
    area: "usage",
  },

  // admin: govern
  {
    key: "users",
    file: "Users.html",
    route: "/admin/users",
    shell: "admin",
    phase: 4,
    built: true,
    area: "users",
  },
  {
    key: "userDetail",
    file: "UserDetail.html",
    route: "/admin/users/[id]",
    shell: "admin",
    phase: 4,
    built: true,
    area: "users",
  },
  {
    key: "groupDetail",
    file: "GroupDetail.html",
    route: "/admin/groups/[id]",
    shell: "admin",
    phase: 4,
    built: true,
    area: "users",
  },
  {
    key: "groupCreate",
    file: "GroupCreate.html",
    route: "/admin/groups/new",
    shell: "admin",
    phase: 4,
    built: true,
    area: "users",
  },
  {
    key: "governance",
    file: "Governance.html",
    route: "/admin/governance",
    shell: "admin",
    phase: 7,
    area: "governance",
  },
  {
    key: "gdprRequest",
    file: "GDPRRequest.html",
    route: "/admin/governance/gdpr/[id]",
    shell: "admin",
    phase: 7,
    area: "governance",
  },
  {
    key: "audit",
    file: "Audit.html",
    route: "/admin/audit",
    shell: "admin",
    phase: 7,
    area: "audit",
  },
] as const;

export function screen(key: string): Screen {
  const found = SCREENS.find((s) => s.key === key);
  if (!found) throw new Error(`unknown screen ${key}`);
  return found;
}

/** A concrete URL for a route pattern, with placeholder ids for dynamic segments. */
export function samplePath(route: string): string {
  return route.replace(/\[[^\]]+\]/g, SAMPLE_ID);
}

/** Admin console navigation, grouped as in the prototype's dark rail. */
export const ADMIN_NAV: readonly {
  section: string | null;
  items: { key: string; href: string; area: AdminArea }[];
}[] = [
  { section: null, items: [{ key: "overview", href: "/admin", area: "overview" }] },
  {
    section: "build",
    items: [
      { key: "bots", href: "/admin/chatbots", area: "chatbots" },
      { key: "automations", href: "/admin/automations", area: "automations" },
      { key: "pipelines", href: "/admin/pipelines", area: "pipelines" },
      { key: "playground", href: "/admin/playground", area: "playground" },
      { key: "dataSources", href: "/admin/sources", area: "sources" },
      { key: "providers", href: "/admin/providers", area: "providers" },
      { key: "mcpServers", href: "/admin/tools", area: "tools" },
      { key: "channels", href: "/admin/channels", area: "channels" },
    ],
  },
  {
    section: "operate",
    items: [
      { key: "conversations", href: "/admin/conversations", area: "conversations" },
      { key: "knowledgeHealth", href: "/admin/knowledge-health", area: "knowledge_health" },
      { key: "evaluation", href: "/admin/evaluation", area: "evaluation" },
      { key: "monitoring", href: "/admin/monitoring", area: "monitoring" },
      { key: "usage", href: "/admin/usage", area: "usage" },
    ],
  },
  {
    section: "govern",
    items: [
      { key: "users", href: "/admin/users", area: "users" },
      { key: "governance", href: "/admin/governance", area: "governance" },
      { key: "audit", href: "/admin/audit", area: "audit" },
    ],
  },
];
