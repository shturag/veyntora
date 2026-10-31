import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("audit log as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("search, change detail, chain status and export", async ({ page }) => {
    await page.goto("/admin/audit");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Audit log");
    await expect(page.getByText("Chain intact")).toBeVisible();
    await expectNoA11yViolations(page);

    await page.getByLabel("Category").selectOption("governance");
    await page.getByLabel("Date range").selectOption("all");
    await page.getByRole("button", { name: "Apply" }).click();
    await page.waitForURL(/category=governance/);
    const detail = page.getByRole("article", { name: "Change detail" });
    await expect(detail).toBeVisible();
    await expect(detail.getByText("Key values are never recorded")).toBeVisible();

    await page.getByRole("button", { name: "Export" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Format").selectOption("jsonl");
    const download = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Export", exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/^audit-log-.*\.jsonl$/);
  });
});
