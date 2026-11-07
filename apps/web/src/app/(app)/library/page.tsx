import { ChatHistory } from "@/components/chat/chat-history";
import { MyFiles } from "@/components/chat/my-files";
import { LibraryHeader } from "@/components/library-header";
import { screenMetadata } from "@/components/screen-placeholder";
import { serverApi } from "@/lib/api/server";

export const generateMetadata = () => screenMetadata("library");

/** Chats & knowledge (prototype: Library.html): the user's conversations and own files. */
export default async function LibraryPage() {
  const api = await serverApi();
  const [{ data }, { data: files }] = await Promise.all([
    api.GET("/v1/chat/conversations", { params: { query: { limit: 200 } } }),
    api.GET("/v1/me/files"),
  ]);
  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6">
      <LibraryHeader current="chats" />
      <div className="grid grid-cols-[minmax(0,1fr)_320px] items-start gap-6 max-[960px]:grid-cols-1">
        <ChatHistory initial={data ?? []} />
        <aside className="flex flex-col gap-4 min-[961px]:sticky min-[961px]:top-6">
          <MyFiles initial={files ?? []} />
        </aside>
      </div>
    </div>
  );
}
