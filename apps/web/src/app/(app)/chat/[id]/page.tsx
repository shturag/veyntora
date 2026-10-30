import { notFound } from "next/navigation";

import { ChatHeaderActions } from "@/components/chat/chat-header-menu";
import { ChatView } from "@/components/chat/chat-view";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("chat");

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ bot?: string; q?: string }>;
};

export default async function ChatPage({ params, searchParams }: Props) {
  const { id } = await params;
  const { bot, q } = await searchParams;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  const api = await serverApi();
  const conv = await api.GET("/v1/chat/threads/{thread_id}", {
    params: { path: { thread_id: id } },
  });

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
  const title = conv.data?.title || q || chatbotName || "";

  return (
    <div className="-mx-8 -my-7 flex min-h-screen flex-col max-[640px]:-mx-4">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-7 py-3.5 max-[640px]:px-4">
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <h1 className="m-0 truncate text-[15px] font-semibold">{title}</h1>
          <span className="text-xs text-fg-muted">{chatbotName}</span>
        </div>
        <ChatHeaderActions conversationId={conv.data?.id} />
      </header>
      <ChatView threadId={id} chatbotId={chatbotId} initialQuestion={conv.data ? undefined : q} />
    </div>
  );
}
