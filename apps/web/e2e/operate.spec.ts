import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("overview and monitoring as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("the overview shows today's numbers; a status message is posted and ended", async ({
    page,
  }) => {
    await page.goto("/admin");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Overview");
    await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "System status" })).toBeVisible();
    await expectNoA11yViolations(page);

    const title = `e2e maintenance ${Date.now()}`;
    await page.getByRole("button", { name: "Post status message to users" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Kind").selectOption("maintenance");
    await dialog.getByLabel("Title").fill(title);
    await dialog.getByLabel("Show for (hours)").fill("1");
    await dialog.getByRole("button", { name: "Post", exact: true }).click();
    await expect(dialog.getByText("Status message posted.")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: `Stop showing “${title}”` }).click();
    await expect(page.getByRole("button", { name: `Stop showing “${title}”` })).toHaveCount(0);
  });

  test("monitoring shows requests by mode for each range", async ({ page }) => {
    await page.goto("/admin/monitoring");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Monitoring");
    await expect(page.getByRole("img", { name: "Requests per hour by mode" })).toBeVisible();
    await expectNoA11yViolations(page);
    await page
      .getByRole("navigation", { name: "Time range", exact: true })
      .getByRole("link", { name: "7 days" })
      .click();
    await expect(page.getByRole("img", { name: "Requests per day by mode" })).toBeVisible();
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await expect(page.getByRole("img", { name: "Requests per day by mode" })).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
