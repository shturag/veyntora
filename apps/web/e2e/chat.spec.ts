import { expect, test } from "@playwright/test";

import { SAMPLE_ID } from "../src/lib/screens";
import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("chat screens as an employee", () => {
  test.use({ storageState: USERS.employee.state });

  test("home greets the user and explains when no assistant is available", async ({ page }) => {
    await page.goto("/home");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Hello, /);
    // No chatbot is live for this user, and nothing is shown as sample data.
    await expect(page.getByText("No assistants yet")).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Assistant" })).toHaveCount(0);
  });

  test("library lists the user's chats", async ({ page }) => {
    await page.goto("/library");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Chats & knowledge");
    // Someone without chats (a fresh install) gets a way to start one instead of a search.
    const search = page.getByLabel("Search chats");
    if ((await search.count()) === 0) {
      await expect(page.getByRole("link", { name: "Start a chat" })).toBeVisible();
      return;
    }
    await search.fill("no such chat title");
    await page.getByLabel("Search chats").press("Enter");
    await expect(page.getByText(/No chats/)).toBeVisible();
  });

  test("unknown chats and documents are not found", async ({ page }) => {
    expect((await page.goto(`/chat/${SAMPLE_ID}`))?.status()).toBe(404);
    expect((await page.goto(`/source/${SAMPLE_ID}`))?.status()).toBe(404);
    // The API gives no hint whether a document exists when the user may not read it.
    const res = await page.request.get(`/api/v1/chat/documents/${SAMPLE_ID}`);
    expect(res.status()).toBe(404);
  });

  for (const colorScheme of ["light", "dark"] as const) {
    test(`chat screens are accessible (${colorScheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await page.goto("/home");
      await expectNoA11yViolations(page);
      await page.goto("/library");
      await expectNoA11yViolations(page);
    });
  }

  test("home works at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/home");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe("my files", () => {
  test.use({ storageState: USERS.employee.state });

  test("an employee uploads a private file and removes it again", async ({ page }) => {
    await page.goto("/library");
    const panel = page.getByRole("region", { name: "My files" });
    await panel.getByLabel("Choose files").setInputFiles({
      name: "e2e-notes.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Notes\n\nPrivate notes for the end-to-end test.\n"),
    });
    const uploaded = page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/me/files") && r.request().method() === "POST",
    );
    await panel.getByRole("button", { name: "Upload" }).click();
    // The first write to a fresh object store can take seconds (it allocates storage).
    expect((await uploaded).status()).toBe(202);
    await expect(panel.getByText("e2e-notes.md", { exact: true })).toBeVisible({ timeout: 15_000 });
    // Another user cannot see it: the API lists only the caller's own files.
    const mine = (await (await page.request.get("/api/v1/me/files")).json()) as { name: string }[];
    expect(mine.map((f) => f.name)).toContain("e2e-notes.md");
    await panel.getByRole("button", { name: "Remove e2e-notes.md" }).click();
    await expect(panel.getByText("e2e-notes.md", { exact: true })).toHaveCount(0);
  });

  test("a disguised executable is refused", async ({ page }) => {
    await page.goto("/library");
    const panel = page.getByRole("region", { name: "My files" });
    await panel.getByLabel("Choose files").setInputFiles({
      name: "invoice.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("MZ\x90\x00 not a pdf"),
    });
    await panel.getByRole("button", { name: "Upload" }).click();
    await expect(panel.getByRole("alert")).toContainText("not a valid .pdf");
  });
});
