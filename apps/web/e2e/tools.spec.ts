import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("tools (MCP) as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("lists servers and the built-in document search", async ({ page }) => {
    await page.goto("/admin/tools");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tools (MCP)");
    await expect(page.getByRole("heading", { name: "Built-in: document search" })).toBeVisible();
    expect(await page.content()).not.toMatch(/kv\/mcp\//);
    await expectNoA11yViolations(page);
  });

  test("register asks for what the chosen authentication needs", async ({ page }) => {
    await page.goto("/admin/tools/new");
    const form = page.getByRole("form", { name: "Connect" });
    const secret = form.locator('input[name="secret"]');
    await expect(secret).toBeVisible();
    await form.getByLabel("OAuth 2.1 service account").check();
    await expect(form.getByLabel("Token URL")).toBeVisible();
    await expect(form.getByText("Client secret")).toBeVisible();
    await form.getByLabel("No authentication").check();
    await expect(secret).toHaveCount(0);
    // Passing the user's token through: no key, the tool's audience instead.
    await form.getByRole("radio", { name: /Pass the user's token through/ }).check();
    await expect(form.getByLabel(/^Audience/)).toBeVisible();
    await expect(secret).toHaveCount(0);
    await expectNoA11yViolations(page);
  });
});
