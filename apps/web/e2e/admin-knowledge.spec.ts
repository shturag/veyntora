import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("providers and data sources as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("providers list instances without ever showing a key", async ({ page }) => {
    await page.goto("/admin/providers");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Providers and keys");
    await expect(page.getByRole("navigation", { name: "Filter by capability" })).toBeVisible();
    const html = await page.content();
    expect(html).not.toMatch(/kv\/providers\//); // no OpenBao paths in the page
    expect(html).not.toMatch(/\?version=\d/); // nor replaced-key versions
  });

  test("the editor offers a fallback, usage and a grace period for key changes", async ({
    page,
  }) => {
    await page.goto("/admin/providers");
    const editor = page
      .getByRole("region", { name: /./ })
      .filter({ has: page.getByText("Fallback provider") });
    if ((await editor.count()) === 0) test.skip(true, "no providers in this database");
    await expect(editor.getByLabel("Fallback provider")).toBeVisible();
    await expect(editor.getByRole("heading", { name: "Usage, last 30 days" })).toBeVisible();
    if (await editor.getByText(/••••/).count()) {
      await expect(editor.getByLabel("Old key keeps working")).toHaveValue("24h");
    }
    await expectNoA11yViolations(page);
  });

  test("add provider offers only adapters the backend has", async ({ page }) => {
    await page.goto("/admin/providers/new");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add provider");
    await page.getByRole("radio", { name: "Embeddings" }).click();
    const adapters = page.getByRole("radiogroup", { name: "2. Adapter" });
    await expect(adapters.getByRole("radio")).toHaveText([/OpenAI-compatible/, /TEI/, /Voyage AI/]);
    await adapters.getByRole("radio", { name: /Voyage AI/ }).click();
    await expect(page.getByText(/External: data leaves your network/)).toBeVisible();
    await expect(page.getByLabel("API key")).toHaveAttribute("type", "password");
  });

  test("connect source shows SharePoint settings and keeps other connectors disabled", async ({
    page,
  }) => {
    await page.goto("/admin/sources/new");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Connect data source");
    await page.getByRole("radio", { name: /SharePoint Online/ }).click();
    await expect(page.getByLabel("Site address")).toBeVisible();
    await expect(page.getByLabel("Client secret")).toHaveAttribute("type", "password");
    await expect(page.getByRole("button", { name: "Confluence" })).toBeDisabled();
  });

  test("data sources list opens a source with its documents", async ({ page }) => {
    await page.goto("/admin/sources");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Data sources");
    const first = page.getByRole("table").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no sources in this database");
    await first.click();
    await expect(page.getByRole("heading", { level: 2, name: /documents?$/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sync now" })).toBeVisible();
  });

  for (const colorScheme of ["light", "dark"] as const) {
    test(`admin knowledge screens are accessible (${colorScheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      for (const path of [
        "/admin/providers",
        "/admin/providers/new",
        "/admin/sources",
        "/admin/sources/new",
      ]) {
        await page.goto(path);
        await expectNoA11yViolations(page);
      }
    });
  }
});
