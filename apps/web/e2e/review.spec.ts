import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("conversations review as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("the queue has the four filters and opens the first rated answer", async ({ page }) => {
    await page.goto("/admin/conversations");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Conversations and feedback");
    const filters = page.getByRole("navigation", { name: "What went wrong" });
    for (const name of ["Not helpful", "Low groundedness", "No answer found", "Guardrail"])
      await expect(filters.getByRole("link", { name: new RegExp(`^${name}`) })).toBeVisible();
    await filters.getByRole("link", { name: /^Not helpful/ }).click();
    await expect(filters.getByRole("link", { name: /^Not helpful/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const answer = page.getByRole("article", { name: "Answer" });
    if (await answer.count()) {
      await expect(answer.getByText("Opening this answer was recorded")).toBeVisible();
    } else {
      await expect(page.getByText("Nothing to review here.")).toBeVisible();
    }
    await expectNoA11yViolations(page);
  });
});
