import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("users & groups as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("lists groups, people and the roles matrix", async ({ page }) => {
    await page.goto("/admin/users");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Users & groups");
    const tabs = page.getByRole("navigation", { name: "Users & groups" });
    await tabs.getByRole("link", { name: "People" }).click();
    await expect(page.getByRole("searchbox").or(page.getByLabel("Search people"))).toBeVisible();
    await tabs.getByRole("link", { name: "Roles & permissions" }).click();
    await expect(page.getByRole("columnheader", { name: "Chatbot admin" })).toBeVisible();
    await tabs.getByRole("link", { name: "Access reviews" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Access reviews");
    await expectNoA11yViolations(page);
  });

  test("creates a manual group, opens it and deletes it again", async ({ page }) => {
    const name = `e2e group ${Date.now()}`;
    await page.goto("/admin/groups/new");
    const form = page.getByRole("form", { name: "New group" });
    await form.getByLabel("Group name").fill(name);
    await form.getByRole("button", { name: "Create group" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
    await expect(page.getByRole("heading", { name: "Role on each chatbot" })).toBeVisible();
    await expectNoA11yViolations(page);
    await page.getByRole("button", { name: "Delete group" }).click();
    await expect(page).toHaveURL(/\/admin\/users$/);
    await expect(page.getByRole("link", { name })).toHaveCount(0);
  });
});
