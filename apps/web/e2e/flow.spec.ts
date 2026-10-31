import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("flow editor as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("shows the flow, adds a step and connects it without saving", async ({ page }) => {
    await page.goto("/admin/chatbots");
    const first = page.getByRole("main").getByRole("listitem").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no chatbots in this database");
    await first.click();
    await page
      .getByRole("navigation", { name: "Chatbot" })
      .getByRole("link", { name: "Pipeline" })
      .click();
    await expect(page.getByRole("region", { name: "Flow" })).toBeVisible();
    await expect(page.getByLabel("Run this flow instead of the standard pipeline")).toBeVisible();
    await page
      .getByRole("navigation", { name: "Steps" })
      .getByRole("button", { name: "+ Condition" })
      .click();
    const details = page.getByRole("complementary", { name: "Step settings" });
    await expect(details.getByLabel("Test")).toBeVisible();
    await details.getByLabel("Test").selectOption("no_sources");
    const connect = page.getByRole("form", { name: "Connect two steps" });
    await connect.getByRole("combobox", { name: "From", exact: true }).selectOption({ index: 1 });
    await connect.getByRole("combobox", { name: "To", exact: true }).selectOption({ index: 2 });
    await connect.getByRole("button", { name: "Connect" }).click();
    await expect(page.getByRole("link", { name: "Settings as forms" })).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
