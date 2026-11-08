import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("usage and budgets as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("a budget is created, changed and deleted; limits saved; the CSV exported", async ({
    page,
  }) => {
    await page.goto("/admin/usage");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Usage and budgets");
    await expectNoA11yViolations(page);

    const code = `E2E-${Date.now()}`;
    await page.getByRole("button", { name: "New budget" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("Applies to").selectOption("cost_centre");
    await dialog.getByLabel("Cost centre", { exact: true }).fill(code);
    await dialog.getByLabel("Budget (EUR)").fill("150");
    await dialog.getByLabel("Block new questions").check();
    await expectNoA11yViolations(page);
    await dialog.getByRole("button", { name: "Save budget" }).click();
    await expect(dialog.getByText("Budget saved.")).toBeVisible();
    await page.keyboard.press("Escape");
    const row = page.getByRole("listitem").filter({ hasText: `cost centre ${code}` });
    await expect(row.getByText("At 100%: new questions are refused.")).toBeVisible();

    await row.getByRole("button", { name: "Edit" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Only warn").check();
    await dialog.getByRole("button", { name: "Save budget" }).click();
    await expect(dialog.getByText("Budget saved.")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(row.getByText("At 100%: owners are warned only.")).toBeVisible();
    page.once("dialog", (d) => void d.accept());
    await row.getByRole("button", { name: `Delete the budget for cost centre ${code}` }).click();
    await expect(row).toHaveCount(0);

    const limits = page.getByRole("form", { name: "Limits per user" });
    await limits.getByLabel("Questions per hour").fill("0");
    await limits.getByRole("button", { name: "Save" }).click();
    await expect(limits.getByText("Limits saved.")).toBeVisible();

    await page.getByRole("button", { name: "Export for finance" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Group by").selectOption("chatbot");
    const download = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Export", exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/^usage-\d{4}-\d{2}-chatbot\.csv$/);
  });
});
