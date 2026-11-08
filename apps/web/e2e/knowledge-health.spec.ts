import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("knowledge health as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("shows the last scan, the numbers and the issues with their actions", async ({ page }) => {
    await page.goto("/admin/knowledge-health");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Knowledge health");
    const kinds = page.getByRole("navigation", { name: "Kinds of findings" });
    for (const kind of [
      "Knowledge gaps",
      "Contradictions",
      "Stale but popular",
      "Duplicates",
      "Reported by readers",
      "Could not be read",
    ]) {
      await expect(kinds.getByRole("link", { name: new RegExp(`^${kind}`) })).toBeVisible();
    }
    await expect(page.getByText(/^(Last scan |No scan yet\.)/)).toBeVisible();
    await expectNoA11yViolations(page);
    await kinds.getByRole("link", { name: /^Could not be read/ }).click();
    await expect(page.getByRole("heading", { name: /^Could not be read/ })).toBeVisible();
    if (
      await page
        .getByText(/could not be read$/)
        .first()
        .isVisible()
    ) {
      const issue = page.locator("li", { has: page.getByText(/could not be read/) }).first();
      await issue.getByRole("button", { name: "Notify owner" }).click();
      await expect(page.getByRole("dialog").getByLabel("Message")).toHaveValue(/could not be read/);
      await expectNoA11yViolations(page);
      await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
      await issue.getByRole("button", { name: "Dismiss" }).click();
      await expect(page.getByRole("radio", { name: "Not a problem" })).toBeChecked();
      await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    }
  });

  test("settings choose the contradiction model; scan now queues a scan", async ({ page }) => {
    await page.goto("/admin/knowledge-health");
    await page.getByRole("button", { name: "Settings" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Model that checks contradictions")).toBeVisible();
    await dialog.getByLabel("Stale after (months)").fill("12");
    await expectNoA11yViolations(page);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog.getByText("Saved.")).toBeVisible();
    await page.keyboard.press("Escape");
    const scan = page.getByRole("button", { name: "Scan now" });
    // While a scan is queued or running the button reads differently and is disabled.
    if ((await scan.count()) && (await scan.isEnabled())) {
      await scan.click();
      await expect(page.getByText("Scan queued; it starts within a minute.")).toBeVisible();
    }
  });
});
