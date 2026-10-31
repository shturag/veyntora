import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("evaluation as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("eval sets: create, add and review cases, import a CSV", async ({ page }) => {
    await page.goto("/admin/evaluation/sets");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Eval sets");
    await page.getByRole("button", { name: "+ New set" }).click();
    const name = `e2e-${Date.now()}`;
    await page.getByRole("dialog").getByLabel("Name").fill(name);
    await page.getByRole("dialog").getByRole("button", { name: "Create set" }).click();
    await expect(page.getByRole("dialog").getByText("Eval set created.")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
    await expectNoA11yViolations(page);

    await page.getByRole("button", { name: "Add case" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("Question").fill("How long is the return window?");
    await dialog.getByLabel("Reference answer").fill("30 days");
    await dialog.getByRole("button", { name: "Save case" }).click();
    await expect(dialog.getByText("Case saved.")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("cell", { name: "How long is the return window?" })).toBeVisible();

    await page.getByRole("button", { name: "Import CSV" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("File").setInputFiles({
      name: "cases.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "question,expected_answer\nHow long is the return window?,30 days\nWho approves refunds over 500 euros?,The team lead\n",
      ),
    });
    await dialog.getByRole("button", { name: "Import" }).click();
    await expect(dialog.getByText("1 cases imported, 1 duplicates skipped.")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.reload();
    await expect(page.getByText(/2 cases/).first()).toBeVisible();
    await page.getByRole("button", { name: "Delete set" }).click();
    await page.waitForURL("**/admin/evaluation/sets");
  });

  test("the evaluation page shows the gate and the judge settings", async ({ page }) => {
    await page.goto("/admin/evaluation");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Evaluation");
    await expect(page.getByRole("form", { name: "Publish gate" })).toBeVisible();
    await expectNoA11yViolations(page);
    await page.getByRole("button", { name: "Settings" }).click();
    await expect(page.getByRole("dialog").getByLabel("Judge model")).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
