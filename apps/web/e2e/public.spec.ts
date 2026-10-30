import { expect, test } from "@playwright/test";

import { expectNoA11yViolations } from "./fixtures";

test.describe("public pages", () => {
  for (const colorScheme of ["light", "dark"] as const) {
    test(`landing page renders and is accessible (${colorScheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Ask your company anything.");
      await expect(page.getByText("API keys ever shown in the UI")).toBeVisible();
      // No sample data from the prototype.
      await expect(page.getByText("1,240 users")).toHaveCount(0);
      await expect(page.getByText("0.94 faithfulness")).toHaveCount(0);
      await expectNoA11yViolations(page);
    });

    test(`sign-in page is accessible (${colorScheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await page.goto("/sign-in");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Veyntora");
      await expect(page.getByText(/Chats are kept for \d+ days/)).toBeVisible();
      await expectNoA11yViolations(page);
    });
  }

  test("status page shows live component status from health checks", async ({ page }) => {
    await page.goto("/status");
    await expect(page.getByTestId("status-overall")).toBeVisible();
    for (const key of ["chat", "agent", "documents", "teams", "signin"]) {
      await expect(page.getByTestId(`status-${key}`)).toBeVisible();
    }
    // Sign-in depends on Keycloak, which the test itself just used.
    await expect(page.getByTestId("status-signin")).toHaveAttribute("data-level", "operational");
    // No Teams channel is configured on a fresh stack.
    await expect(page.getByTestId("status-teams")).toHaveAttribute("data-level", "not_configured");
    await expectNoA11yViolations(page);
  });

  test("the language can be switched to German before sign-in", async ({ page }) => {
    await page.goto("/sign-in");
    await page.getByLabel("Language").selectOption("de");
    await expect(page.getByRole("link", { name: "Mit Firmenkonto anmelden" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "de");
    await page.getByLabel("Sprache").selectOption("en");
    await expect(page.getByRole("link", { name: "Sign in with company account" })).toBeVisible();
  });

  test("protected pages redirect to sign-in and keep the target", async ({ page }) => {
    await page.goto("/admin/providers");
    await expect(page).toHaveURL(/\/sign-in\?return_to=%2Fadmin%2Fproviders/);
  });

  test("the API proxy refuses cookie writes without the CSRF header", async ({ request }) => {
    const res = await request.post("/api/auth/logout", { headers: { cookie: "vey_session=x" } });
    expect(res.status()).toBe(403);
  });
});
