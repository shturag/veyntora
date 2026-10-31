import { expect, test, type Page } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

async function legalRole(page: Page, on: boolean) {
  const roles = page.getByRole("region", { name: "Platform roles" });
  await roles
    .getByRole("listitem")
    .filter({ hasText: "Legal" })
    .getByRole("button", { name: "Edit" })
    .click();
  const dialog = page.getByRole("dialog");
  const box = dialog.getByLabel("platform-admins");
  if (on) await box.check();
  else await box.uncheck();
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog.getByText("Saved.")).toBeVisible();
  await page.keyboard.press("Escape");
}

test.describe("governance as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("settings save; legal holds need the Legal role", async ({ page }) => {
    await page.goto("/admin/governance");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Governance");
    await expectNoA11yViolations(page);
    await expect(page.getByRole("button", { name: "Place hold" })).toBeDisabled();

    const form = page.getByRole("form", { name: "Governance settings" });
    await form.getByLabel("Chat history (days)").fill("90");
    await form.getByRole("button", { name: "Save" }).click();
    await expect(form.getByText("Saved.")).toBeVisible();

    await legalRole(page, true);
    await page.reload();
    const name = `e2e hold ${Date.now()}`;
    await page.getByRole("button", { name: "Place hold" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill(name);
    await dialog.getByLabel("Reason").fill("end-to-end test");
    await dialog.getByLabel("People (e-mail addresses)").fill("employee@veyntora.local");
    await dialog.getByRole("button", { name: "Place hold" }).click();
    await expect(dialog.getByText("Hold placed.")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: `Lift the hold ${name}` }).click();
    await expect(page.getByRole("button", { name: `Lift the hold ${name}` })).toHaveCount(0);
    await legalRole(page, false);
  });

  test("a data subject request: record, verify identity; the requester cannot approve", async ({
    page,
  }) => {
    await page.goto("/admin/governance");
    await page.getByRole("button", { name: "New request" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Kind").selectOption("access");
    await dialog.getByLabel("The person's e-mail address").fill("employee@veyntora.local");
    await dialog.getByLabel("Received via").fill("e2e");
    await dialog.getByRole("button", { name: "Record request" }).click();
    await page.waitForURL(/\/admin\/governance\/gdpr\//);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Export (access) request");
    await expect(page.getByRole("cell", { name: "Chat history" })).toBeVisible();
    await expectNoA11yViolations(page);
    await page.getByRole("button", { name: "Mark identity verified" }).click();
    await expect(page.getByRole("button", { name: "Identity verified" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Approve (DPO)" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Build export" })).toBeDisabled();
  });
});
