import { redirect } from "next/navigation";

/** Saved answers moved into Chats & knowledge; old links keep working. */
export default async function SavedRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string>>;
}) {
  const query = new URLSearchParams(await searchParams).toString();
  redirect(`/library/saved${query ? `?${query}` : ""}`);
}
