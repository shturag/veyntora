import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("integrations and data rules as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("Langfuse and Grafana are set up in the console; keys are write-only", async ({ page }) => {
    await page.goto("/admin/integrations");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Integrations");
    const langfuse = page.getByRole("region", { name: "Langfuse" });
    const grafana = page.getByRole("region", { name: "Grafana" });
    await expect(langfuse.locator('input[name="url"]')).toBeVisible();
    await expect(langfuse.getByRole("radio", { name: /External/ })).toBeVisible();
    await expect(grafana.locator('input[name="url"]')).toBeVisible();
    // A stored key is shown by its last 4 characters at most; the field is always empty.
    for (const card of [langfuse, grafana]) {
      const key = card.locator('input[name="secret"]');
      if (await key.count()) await expect(key).toHaveValue("");
    }
    await expectNoA11yViolations(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await expectNoA11yViolations(page);
  });

  test("monitoring offers Grafana dashboards or says where to set them up", async ({ page }) => {
    await page.goto("/admin/monitoring");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Monitoring");
    const dashboards = page.getByRole("heading", { name: "Grafana dashboards" });
    if (await dashboards.count()) {
      await expect(page.getByRole("navigation", { name: "Dashboard time range" })).toBeVisible();
    } else {
      await page.getByRole("link", { name: "Integrations" }).last().click();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Integrations");
    }
  });

  test("a chatbot's data rule is edited on its Access page", async ({ page }) => {
    await page.goto("/admin/chatbots");
    const first = page.getByRole("main").getByRole("listitem").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no chatbots in this database");
    await first.click();
    await page
      .getByRole("navigation", { name: "Chatbot" })
      .getByRole("link", { name: "Access" })
      .click();
    const rule = page.getByRole("region", { name: "Data rule" });
    await expect(rule).toBeVisible();
    const traces = rule.getByRole("checkbox", { name: "Send traces to an external Langfuse" });
    const before = await traces.isChecked();
    await traces.setChecked(!before);
    await rule.getByRole("button", { name: "Save data rule" }).click();
    await expect(rule.getByRole("status")).toHaveText("Data rule saved.");
    await page.reload();
    await expect(traces).toBeChecked({ checked: !before });
    // Put it back as it was.
    await traces.setChecked(before);
    await rule.getByRole("button", { name: "Save data rule" }).click();
    await expect(rule.getByRole("status")).toHaveText("Data rule saved.");
    await expectNoA11yViolations(page);
  });
});
