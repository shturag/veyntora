import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("access reviews as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("start a round, keep a grant, close the round", async ({ page }) => {
    await page.goto("/admin/access-reviews");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Access reviews");
    const close = page.getByRole("button", { name: "Close round" });
    if (await close.count()) {
      await close.click();
      await expect(page.getByRole("button", { name: "Start a review round" })).toBeVisible();
    }
    await page.getByRole("button", { name: "Start a review round" }).click();
    await expect(page.getByText(/of \d+ decided/)).toBeVisible();
    await expectNoA11yViolations(page);
    const keep = page.getByRole("button", { name: /^Keep / }).first();
    if (await keep.count()) {
      await keep.click();
      await expect(page.getByText(/1 kept/)).toBeVisible();
    }
    await page.getByRole("button", { name: "Close round" }).click();
    await expect(page.getByRole("button", { name: "Start a review round" })).toBeVisible();
  });
});
