/**
 * Every screen mapped to its route.
 *
 * This is the single source for navigation guards and the Playwright route sweep. Titles and
 * summaries live in messages/{en,de}.json under `screens.<key>`.
 */

type Shell = "public" | "user" | "admin" | "wizard";

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

type Screen = {
  key: string;
  /** Next.js route pattern. */
  route: string;
  shell: Shell;
  area?: AdminArea;
  /** For screens that are states of another route rather than their own page. */
  stateOf?: string;
};

export const SAMPLE_ID = "00000000-0000-0000-0000-000000000000";

export const SCREENS: readonly Screen[] = [
  // public
  { key: "landing", route: "/", shell: "public" },
  { key: "signIn", route: "/sign-in", shell: "public" },
  { key: "status", route: "/status", shell: "public" },
  { key: "help", route: "/help", shell: "public" },

  // user app
  { key: "home", route: "/home", shell: "user" },
  { key: "chat", route: "/chat/[id]", shell: "user" },
  {
    key: "chatFast",
    route: "/chat/[id]",
    shell: "user",
    stateOf: "chat",
  },
  {
    key: "agentRunning",
    route: "/chat/[id]",
    shell: "user",
    stateOf: "chat",
  },
  {
    key: "chatStates",
    route: "/chat/[id]",
    shell: "user",
    stateOf: "chat",
  },
  {
    key: "mobile",
    route: "/chat/[id]",
    shell: "user",
    stateOf: "chat",
  },
  {
    key: "source",
    route: "/source/[id]",
    shell: "user",
  },
  { key: "library", route: "/library", shell: "user" },
  {
    key: "savedAnswers",
    route: "/library/saved",
    shell: "user",
  },
  {
    key: "approvals",
    route: "/approvals",
    shell: "user",
  },
  { key: "handoff", route: "/handoff", shell: "user" },
  {
    key: "settings",
    route: "/settings",
    shell: "user",
  },

  // admin: overview and chatbots
  {
    key: "overview",
    route: "/admin",
    shell: "admin",
    area: "overview",
  },
  {
    key: "bots",
    route: "/admin/chatbots",
    shell: "admin",
    area: "chatbots",
  },
  {
    key: "botOverview",
    route: "/admin/chatbots/[id]",
    shell: "admin",
    area: "chatbots",
  },
  {
    key: "botFlow",
    route: "/admin/chatbots/[id]/flow",
    shell: "admin",
    area: "chatbots",
  },
  {
    key: "botKnowledge",
    route: "/admin/chatbots/[id]/knowledge",
    shell: "admin",
    area: "chatbots",
  },
  {
    key: "botAccess",
    route: "/admin/chatbots/[id]/access",
    shell: "admin",
    area: "chatbots",
  },
  {
    key: "versions",
    route: "/admin/chatbots/[id]/versions",
    shell: "admin",
    area: "chatbots",
  },

  // admin: new chatbot wizard
  {
    key: "botCreate",
    route: "/admin/chatbots/new",
    shell: "wizard",
    area: "chatbots",
  },
  {
    key: "botCreateKnowledge",
    route: "/admin/chatbots/new/knowledge",
    shell: "wizard",
    area: "chatbots",
  },
  {
    key: "botCreatePipeline",
    route: "/admin/chatbots/new/pipeline",
    shell: "wizard",
    area: "chatbots",
  },
  {
    key: "botCreateAccess",
    route: "/admin/chatbots/new/access",
    shell: "wizard",
    area: "chatbots",
  },
  {
    key: "botCreatePublish",
    route: "/admin/chatbots/new/publish",
    shell: "wizard",
    area: "chatbots",
  },

  // admin: pipelines (per chatbot)
  {
    key: "pipeline",
    route: "/admin/pipelines/[botId]",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "pipelineIngestion",
    route: "/admin/pipelines/[botId]/ingestion",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "pipelineRerank",
    route: "/admin/pipelines/[botId]/rerank",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "pipelineGeneration",
    route: "/admin/pipelines/[botId]/generation",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "pipelineAgent",
    route: "/admin/pipelines/[botId]/agent",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "pipelineRouter",
    route: "/admin/pipelines/[botId]/router",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "pipelineGuardrails",
    route: "/admin/pipelines/[botId]/guardrails",
    shell: "admin",
    area: "pipelines",
  },
  {
    key: "playground",
    route: "/admin/playground",
    shell: "admin",
    area: "playground",
  },

  // admin: data, providers, tools, channels
  {
    key: "dataSources",
    route: "/admin/sources",
    shell: "admin",
    area: "sources",
  },
  {
    key: "connectSource",
    route: "/admin/sources/new",
    shell: "admin",
    area: "sources",
  },
  {
    key: "sourceDetail",
    route: "/admin/sources/[id]",
    shell: "admin",
    area: "sources",
  },
  {
    key: "providers",
    route: "/admin/providers",
    shell: "admin",
    area: "providers",
  },
  {
    key: "addProvider",
    route: "/admin/providers/new",
    shell: "admin",
    area: "providers",
  },
  {
    key: "mcpServers",
    route: "/admin/tools",
    shell: "admin",
    area: "tools",
  },
  {
    key: "mcpRegister",
    route: "/admin/tools/new",
    shell: "admin",
    area: "tools",
  },
  {
    key: "mcpServerDetail",
    route: "/admin/tools/[id]",
    shell: "admin",
    area: "tools",
  },
  {
    key: "channels",
    route: "/admin/channels",
    shell: "admin",
    area: "channels",
  },

  // admin: automations
  {
    key: "automations",
    route: "/admin/automations",
    shell: "admin",
    area: "automations",
  },
  {
    key: "automationNew",
    route: "/admin/automations/new",
    shell: "admin",
    area: "automations",
  },
  {
    key: "automationBuilder",
    route: "/admin/automations/[id]",
    shell: "admin",
    area: "automations",
  },
  {
    key: "automationTrigger",
    route: "/admin/automations/[id]/trigger",
    shell: "admin",
    area: "automations",
  },
  {
    key: "automationAgentStep",
    route: "/admin/automations/[id]/agent-step/[stepId]",
    shell: "admin",
    area: "automations",
  },
  {
    key: "automationApprovalStep",
    route: "/admin/automations/[id]/approval-step/[stepId]",
    shell: "admin",
    area: "automations",
  },
  {
    key: "runTrace",
    route: "/admin/runs/[id]",
    shell: "admin",
    area: "automations",
  },

  // admin: operate
  {
    key: "conversations",
    route: "/admin/conversations",
    shell: "admin",
    area: "conversations",
  },
  {
    key: "knowledgeHealth",
    route: "/admin/knowledge-health",
    shell: "admin",
    area: "knowledge_health",
  },
  {
    key: "evaluation",
    route: "/admin/evaluation",
    shell: "admin",
    area: "evaluation",
  },
  {
    key: "evalSets",
    route: "/admin/evaluation/sets",
    shell: "admin",
    area: "evaluation",
  },
  {
    key: "monitoring",
    route: "/admin/monitoring",
    shell: "admin",
    area: "monitoring",
  },
  {
    key: "usage",
    route: "/admin/usage",
    shell: "admin",
    area: "usage",
  },

  // admin: govern
  {
    key: "users",
    route: "/admin/users",
    shell: "admin",
    area: "users",
  },
  {
    key: "userDetail",
    route: "/admin/users/[id]",
    shell: "admin",
    area: "users",
  },
  {
    key: "groupDetail",
    route: "/admin/groups/[id]",
    shell: "admin",
    area: "users",
  },
  {
    key: "groupCreate",
    route: "/admin/groups/new",
    shell: "admin",
    area: "users",
  },
  {
    key: "governance",
    route: "/admin/governance",
    shell: "admin",
    area: "governance",
  },
  {
    key: "gdprRequest",
    route: "/admin/governance/gdpr/[id]",
    shell: "admin",
    area: "governance",
  },
  {
    key: "audit",
    route: "/admin/audit",
    shell: "admin",
    area: "audit",
  },
] as const;

/** A concrete URL for a route pattern, with placeholder ids for dynamic segments. */
export function samplePath(route: string): string {
  return route.replace(/\[[^\]]+\]/g, SAMPLE_ID);
}

/** Admin console navigation, in sections. */
/** An item is shown to holders of its area, or (platformAdmin) to platform admins only. */
type AdminNavItem = { key: string; href: string } & (
  { area: AdminArea; platformAdmin?: never } | { area?: never; platformAdmin: true }
);

export const ADMIN_NAV: readonly {
  section: string | null;
  items: AdminNavItem[];
}[] = [
  { section: null, items: [{ key: "overview", href: "/admin", area: "overview" }] },
  {
    section: "build",
    items: [
      { key: "bots", href: "/admin/chatbots", area: "chatbots" },
      { key: "pipelines", href: "/admin/pipelines", area: "pipelines" },
      { key: "automations", href: "/admin/automations", area: "automations" },
      { key: "playground", href: "/admin/playground", area: "playground" },
    ],
  },
  {
    section: "knowledge",
    items: [
      { key: "dataSources", href: "/admin/sources", area: "sources" },
      { key: "knowledgeHealth", href: "/admin/knowledge-health", area: "knowledge_health" },
      { key: "evaluation", href: "/admin/evaluation", area: "evaluation" },
    ],
  },
  {
    section: "connect",
    items: [
      { key: "providers", href: "/admin/providers", area: "providers" },
      { key: "mcpServers", href: "/admin/tools", area: "tools" },
      { key: "channels", href: "/admin/channels", area: "channels" },
      { key: "integrations", href: "/admin/integrations", area: "monitoring" },
    ],
  },
  {
    section: "operate",
    items: [
      { key: "conversations", href: "/admin/conversations", area: "conversations" },
      { key: "monitoring", href: "/admin/monitoring", area: "monitoring" },
      { key: "usage", href: "/admin/usage", area: "usage" },
      { key: "infrastructure", href: "/admin/infrastructure", platformAdmin: true },
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
