import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("pipeline editor as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("edits the draft, validates input and restores it", async ({ page }) => {
    await page.goto("/admin/pipelines");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Pipelines");
    const first = page.getByRole("main").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no chatbots in this database");
    await first.click();
    const steps = page.getByRole("navigation", { name: "Pipeline steps" });
    await expect(steps).toBeVisible();
    // Ingestion, step 1, opens first.
    await expect(page.getByRole("heading", { level: 2, name: "Ingestion" })).toBeVisible();
    await steps.getByRole("link", { name: /Retrieval/ }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Retrieval" })).toBeVisible();

    const form = page.getByRole("form", { name: "Retrieval" });
    const topK = page.getByLabel("Top-k candidates");
    const original = await topK.inputValue();
    await topK.fill(original === "21" ? "22" : "21");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByRole("form", { name: "Retrieval" }).getByRole("status")).toHaveText(
      "Draft saved.",
    );

    // A filter on a key that is not indexed is refused with the reason.
    await page.getByLabel("Metadata filter").fill("acl in [user:x]");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(form.getByRole("alert")).toContainText("cannot be filtered");

    await page.reload();
    await page.getByLabel("Top-k candidates").fill(original);
    await page.getByLabel("Metadata filter").fill("");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByRole("form", { name: "Retrieval" }).getByRole("status")).toHaveText(
      "Draft saved.",
    );
  });

  test("every section opens and is accessible", async ({ page }) => {
    await page.goto("/admin/pipelines");
    const first = page.getByRole("main").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no chatbots in this database");
    await first.click();
    for (const name of ["Ingestion", "Reranking", "Generation", "Agent", "Router", "Guardrails"]) {
      await page
        .getByRole("navigation", { name: "Pipeline steps" })
        .getByRole("link", { name: new RegExp(name) })
        .click();
      await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
    }
    await expect(page.getByLabel("PII provider")).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
