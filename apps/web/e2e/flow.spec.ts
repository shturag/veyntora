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
    const mode = page.getByRole("radiogroup", { name: "How this chatbot runs" });
    await expect(mode.getByRole("radio", { name: "Standard pipeline" })).toBeVisible();
    // The standard pipeline is read-only on the canvas; a custom flow is edited.
    await mode.getByRole("radio", { name: "Custom flow" }).click();
    await page
      .getByRole("navigation", { name: "Steps" })
      .getByRole("button", { name: /^Condition/ })
      .click();
    const details = page.getByRole("complementary", { name: "Step settings" });
    await expect(details.getByLabel("Test")).toBeVisible();
    await details.getByLabel("Test").selectOption("no_sources");
    await details.getByText("Connect two steps").click();
    const connect = page.getByRole("form", { name: "Connect two steps" });
    await connect.getByRole("combobox", { name: "From", exact: true }).selectOption({ index: 1 });
    await connect.getByRole("combobox", { name: "To", exact: true }).selectOption({ index: 2 });
    await connect.getByRole("button", { name: "Connect" }).click();
    await expect(page.getByText("Unsaved changes")).toBeVisible();
    await expect(page.getByRole("link", { name: "Settings as forms" })).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
