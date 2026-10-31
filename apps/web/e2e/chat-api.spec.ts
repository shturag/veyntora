import { expect, test } from "@playwright/test";

import { signIn, USERS } from "./fixtures";

const CSRF = { "X-Veyntora-CSRF": "1" };
const NO_SUCH_BOT = "00000000-0000-4000-8000-000000000000";

test.describe("chat proxy to the graph server", () => {
  test("refuses without a session", async ({ request }) => {
    const res = await request.post("/api/v1/chat/lg/threads", { data: {}, headers: CSRF });
    expect(res.status()).toBe(401);
  });

  test("only lets chat calls through and checks chatbot access", async ({ page }) => {
    await signIn(page, USERS.employee);
    const api = page.request;

    const thread = await api.post("/api/v1/chat/lg/threads", {
      data: { metadata: { owner: "someone-else" } },
      headers: CSRF,
    });
    expect(thread.status()).toBe(200);
    const { thread_id } = (await thread.json()) as { thread_id: string };
    expect(thread_id).toMatch(/^[0-9a-f-]{36}$/);

    // Graph server endpoints the chat does not need stay hidden.
    expect(
      (await api.post("/api/v1/chat/lg/assistants/search", { data: {}, headers: CSRF })).status(),
    ).toBe(404);
    expect(
      (
        await api.post(`/api/v1/chat/lg/threads/${thread_id}/state`, { data: {}, headers: CSRF })
      ).status(),
    ).toBe(404);

    const run = await api.post(`/api/v1/chat/lg/threads/${thread_id}/runs/stream`, {
      data: {
        input: { chatbot_id: NO_SUCH_BOT, messages: [{ type: "human", content: "Hello?" }] },
        stream_mode: ["values"],
      },
      headers: CSRF,
    });
    expect(run.status()).toBe(403);
  });
});
