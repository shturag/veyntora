import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("saved answers, expert questions and notifications", () => {
  test.use({ storageState: USERS.employee.state });

  test("saved answers list both scopes", async ({ page }) => {
    await page.goto("/saved");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Saved answers");
    await expect(page.getByRole("link", { name: "Shared with my team" })).toBeVisible();
    await expectNoA11yViolations(page);
    await page.getByRole("link", { name: "Shared with my team" }).click();
    await expect(page.getByRole("link", { name: "Shared with my team" })).toHaveAttribute("aria-current", "page");
  });

  test("expert questions and notifications open from the sidebar", async ({ page }) => {
    await page.goto("/home");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Expert questions" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Expert questions");
    await expect(page.getByRole("heading", { name: "My questions" })).toBeVisible();
    await expectNoA11yViolations(page);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /^Notifications/ }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Notifications");
    await expectNoA11yViolations(page);
  });

  test("a hand-off form for an unknown answer says so", async ({ page }) => {
    await page.goto("/handoff?message=00000000-0000-4000-8000-000000000000");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Ask a human expert");
    await expect(page.getByText("This answer was not found.")).toBeVisible();
  });

  test("a shared chat link that is not for me is not found", async ({ page }) => {
    const res = await page.goto("/shared/00000000-0000-4000-8000-000000000000");
    expect(res?.status()).toBe(404);
  });
});

test.describe("chatbot experts as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("the access page chooses the expert teams", async ({ page }) => {
    await page.goto("/admin/chatbots");
    const first = page.locator('a[href^="/admin/chatbots/"]').filter({ hasNotText: "New" }).first();
    test.skip((await first.count()) === 0, "no chatbot on this stack yet");
    const href = await first.getAttribute("href");
    await page.goto(`${href}/access`);
    await expect(page.getByRole("heading", { name: "Experts for hand-off" })).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
