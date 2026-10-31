import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("agent screens as an employee", () => {
  test.use({ storageState: USERS.employee.state });

  test("the approvals inbox has its three views", async ({ page }) => {
    await page.goto("/approvals");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Approvals");
    const tabs = page.getByRole("navigation", { name: "Approvals" });
    await expect(tabs.getByRole("link")).toHaveText(["To decide", "My requests", "Decided by me"]);
    await tabs.getByRole("link", { name: "My requests" }).click();
    await expect(tabs.getByRole("link", { name: "My requests" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expectNoA11yViolations(page);
  });

  test("the question box lets the user choose Auto, Fast or Agent", async ({ page }) => {
    await page.goto("/home");
    const modes = page.getByRole("radiogroup", { name: "Answer mode" });
    if ((await modes.count()) === 0) test.skip(true, "no assistant for this user");
    await modes.getByRole("radio", { name: "Agent" }).click();
    await expect(modes.getByRole("radio", { name: "Agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(modes.getByRole("radio", { name: "Auto" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });
});

test.describe("agent settings as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("the Agent page binds tools", async ({ page }) => {
    await page.goto("/admin/pipelines");
    const first = page.getByRole("main").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no chatbots in this database");
    await first.click();
    await page
      .getByRole("navigation", { name: "Pipeline steps" })
      .getByRole("link", { name: /Agent/ })
      .click();
    await expect(page.getByRole("group", { name: "Tools" })).toBeVisible();
    await expect(page.getByText(/takes effect in Phase 3/)).toHaveCount(0);
    await expectNoA11yViolations(page);
  });
});
