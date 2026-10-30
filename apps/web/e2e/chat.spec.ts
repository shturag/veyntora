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
    await expect(page.getByRole("searchbox").or(page.getByLabel("Search chats"))).toBeVisible();
    await page.getByLabel("Search chats").fill("no such chat title");
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
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
