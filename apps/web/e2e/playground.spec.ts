import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("playground as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("runs a question against the draft through the graph server", async ({ page }) => {
    await page.goto("/admin/playground");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Playground");
    const form = page.getByRole("form", { name: "Test query" });
    if ((await form.count()) === 0) test.skip(true, "no chatbots in this database");
    // The Playground tests Fast; Agent and Auto runs are tested in chat.
    await expect(form.getByText("Fast mode", { exact: true })).toBeVisible();
    const run = form.getByRole("button", { name: /Run (both|draft)/ });
    await expect(run).toBeDisabled();
    await form.getByLabel("Question").fill("What is the refund period?");
    await run.click();
    const draft = page.getByRole("article", { name: "Draft" });
    // Without model keys the draft cannot be set up completely; either way the API, the
    // graph server and the tester's permissions were all involved.
    await expect(
      draft.getByRole("heading", { level: 3, name: /^(Answer|Why it did not run)$/ }),
    ).toBeVisible({ timeout: 60_000 });
    await expectNoA11yViolations(page);
  });
});
