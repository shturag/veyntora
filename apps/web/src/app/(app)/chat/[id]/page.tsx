import { notFound } from "next/navigation";

import { ChatHeaderActions } from "@/components/chat/chat-header-menu";
import { ChatView } from "@/components/chat/chat-view";
import type { AttachedFile } from "@/lib/chat";
import { MODES } from "@/lib/chat";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";
import { getPublicInfo } from "@/lib/public-info";

export const generateMetadata = () => screenMetadata("chat");

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    bot?: string;
    q?: string;
    mode?: string;
    files?: string;
    model?: string;
    thinking?: string;
    web?: string;
    code?: string;
  }>;
};

export default async function ChatPage({ params, searchParams }: Props) {
  const { id } = await params;
  const { bot, q, mode, files, model, thinking, web, code } = await searchParams;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const api = await serverApi();
  const [conv, { data: prefs }] = await Promise.all([
    api.GET("/v1/chat/threads/{thread_id}", { params: { path: { thread_id: id } } }),
    api.GET("/v1/me/preferences"),
  ]);
  const initialMode = MODES.find((m) => m === mode) ?? prefs?.default_mode ?? "auto";

  let chatbotId = conv.data?.chatbot_id;
  let chatbotName = conv.data?.chatbot_name;
  if (!chatbotId && bot) {
    // A new thread from Home: the conversation is stored with the first answer.
    const { data: bots } = await api.GET("/v1/me/chatbots");
    const match = (bots ?? []).find((b) => b.id === bot);
    chatbotId = match?.id;
    chatbotName = match?.name;
  }
  if (!chatbotId) notFound();
  const info = await getPublicInfo();
  const title = conv.data?.title || q || chatbotName || "";

  return (
    <div className="-mx-8 -my-7 flex min-h-screen flex-col max-[640px]:-mx-4">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-7 py-3.5 max-[640px]:px-4">
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <h1 className="m-0 truncate text-[15px] font-semibold">{title}</h1>
          <span className="text-xs text-fg-muted">{chatbotName}</span>
        </div>
        <ChatHeaderActions conversationId={conv.data?.id} threadId={id} />
      </header>
      <ChatView
        threadId={id}
        chatbotId={chatbotId}
        initialMode={initialMode}
        showSteps={prefs?.show_agent_steps ?? true}
        initialQuestion={conv.data ? undefined : q}
        initialFiles={conv.data ? undefined : filesOf(files)}
        initialChoices={{
          model,
          thinking: thinking === "1",
          webSearch: web === "1",
          code: code === "1",
        }}
        aiNotice={info?.ai_notice}
      />
    </div>
  );
}

/** Files attached on Home to the first question (the server checks they are the asker's). */
function filesOf(raw?: string): AttachedFile[] | undefined {
  if (!raw) return undefined;
  try {
    const list: unknown = JSON.parse(raw);
    if (!Array.isArray(list)) return undefined;
    return list
      .filter(
        (f): f is AttachedFile =>
          typeof f === "object" &&
          f !== null &&
          typeof f.id === "string" &&
          typeof f.name === "string",
      )
      .slice(0, 5);
  } catch {
    return undefined;
  }
}
