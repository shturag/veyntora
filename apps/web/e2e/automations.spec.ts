import { expect, test, type Page } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

async function newFromTemplate(page: Page, template: string): Promise<string> {
  await page.goto("/admin/automations/new");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("New automation");
  await page.getByRole("button", { name: new RegExp(template) }).click();
  await page.waitForURL(/\/admin\/automations\/[0-9a-f-]{36}$/);
  return page.url().split("/").pop()!;
}

test.describe("automations as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("the list shows this week's numbers and the incident switch", async ({ page }) => {
    await page.goto("/admin/automations");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Automations");
    for (const kpi of ["Active", "Runs this week", "Waiting for approval"]) {
      await expect(page.getByText(kpi, { exact: true })).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "+ New automation" })).toBeVisible();
    await expectNoA11yViolations(page);
  });

  test("a draft from scratch: trigger, a step, its problems, and a dry run", async ({ page }) => {
    const id = await newFromTemplate(page, "Start from scratch");
    await expect(page.getByText("Draft", { exact: true })).toBeVisible();
    await expect(page.getByText("Add at least one step.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Activate" })).toBeDisabled();
    await expect(page.getByText(/^Automation: /)).toBeVisible(); // its own service identity
    await expectNoA11yViolations(page);

    // The trigger: weekly on Wednesday, with the next runs shown before saving.
    await page.goto(`/admin/automations/${id}/trigger`);
    await page.getByRole("checkbox", { name: "Wed" }).check();
    await expect(page.getByText(/^Next runs: /)).toBeVisible();
    await page.getByRole("radio", { name: "Daily" }).check();
    await page.getByRole("radio", { name: "Weekly" }).check();
    await expectNoA11yViolations(page);
    await page.getByRole("button", { name: "Save trigger" }).click();
    await page.waitForURL(new RegExp(`/admin/automations/${id}$`));
    await expect(page.getByText(/^Next runs: /)).toBeVisible();

    // A notification without an approval before it, as the safety rule says. Steps are
    // added and edited in place, on the automation's page.
    await page.getByRole("button", { name: "Add step" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /^Notify/ })
      .click();
    await page.getByRole("textbox", { name: "Message", exact: true }).fill("Report: {event.key}");
    await expectNoA11yViolations(page);
    await page.getByRole("button", { name: "Save step" }).click();
    await expect(page.getByRole("button", { name: "Save step" })).toHaveCount(0);
    expect(new URL(page.url()).pathname).toBe(`/admin/automations/${id}`);
    await expect(
      page.getByText("Step 1: a notification needs an approval step before it."),
    ).toBeVisible();
    await expect(page.getByText("Step 1: choose the channel to post in.")).toBeVisible();

    // A dry run takes no actions; the run trace shows what would have happened.
    await page.getByRole("button", { name: "Test with sample" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Input (optional, JSON)").fill('{"key": "SUP-4821"}');
    await dialog.getByRole("button", { name: "Run now" }).click();
    await dialog.getByRole("link", { name: "Follow the run →" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("SUP-4821");
    await expect(page.getByText("Dry run", { exact: true })).toBeVisible();
    await expect(async () => {
      await page.reload();
      await expect(page.getByText("Succeeded", { exact: true })).toBeVisible({ timeout: 1000 });
    }).toPass({ timeout: 60_000 });
    await expect(page.getByText(/would send to teams channel/)).toBeVisible();
    await expectNoA11yViolations(page);
  });

  test("an event trigger gets a webhook token that is shown once", async ({ page }) => {
    const id = await newFromTemplate(page, "Triage new tickets");
    await expect(page.getByRole("heading", { name: "Webhook" })).toBeVisible();
    await expect(page.getByText("No token yet.")).toBeVisible();
    await page.getByRole("button", { name: "Create token" }).click();
    const token = page.locator("code", { hasText: /^vey_wh_/ });
    await expect(token).toBeVisible();
    await expect(page.getByText(/\/api\/v1\/hooks\/automations$/)).toBeVisible();
    await page.reload();
    await expect(page.locator("code", { hasText: /^vey_wh_/ })).toHaveCount(0);
    await expect(page.getByText(/^Current token: vey_wh_[0-9a-f]{12}…$/)).toBeVisible();

    // The approval step is edited with the actions after it.
    await page.goto(`/admin/automations/${id}/approval-step/step2`);
    await expect(page.getByRole("heading", { name: /Human approval/ }).first()).toBeVisible();
    await expect(page.getByLabel("Approver may correct")).toHaveValue("step1.draft_note");
    await expect(page.getByRole("heading", { name: /Notify/ })).toBeVisible();
    await expectNoA11yViolations(page);
  });
});
