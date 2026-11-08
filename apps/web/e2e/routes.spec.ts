import { expect, test } from "@playwright/test";

import { samplePath, SCREENS } from "../src/lib/screens";
import { expectNoA11yViolations, signIn, USERS } from "./fixtures";

// One entry per route; screens that are states of another route are covered by it.
const routed = SCREENS.filter((s) => !s.stateOf && s.shell !== "public");

test.describe("as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("admin rail lists every area", async ({ page }) => {
    await page.goto("/admin");
    const nav = page.getByRole("navigation", { name: "Admin" });
    for (const label of ["Overview", "Chatbots", "Providers & keys", "Tools (MCP)", "Audit log"]) {
      await expect(nav.getByRole("link", { name: label, exact: true })).toBeVisible();
    }
    await expect(nav.getByRole("link", { name: "Overview", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  for (const colorScheme of ["light", "dark"] as const) {
    test(`user and admin shells are accessible (${colorScheme})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await page.goto("/home");
      await expectNoA11yViolations(page);
      await page.goto("/admin/providers");
      await expectNoA11yViolations(page);
      await page.goto("/admin/chatbots/new");
      await expectNoA11yViolations(page);
    });
  }

  test("the account menu switches the language to German", async ({ page }) => {
    await page.goto("/home");
    await page.getByRole("button", { name: /Account menu/ }).click();
    await page.getByRole("menuitemradio", { name: "Deutsch" }).click();
    await expect(
      page
        .getByRole("navigation", { name: "Hauptmenü" })
        .getByRole("link", { name: "Start", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Kontomenü/ }).click();
    await page.getByRole("menuitemradio", { name: "English" }).click();
    await expect(
      page
        .getByRole("navigation", { name: "Main" })
        .getByRole("link", { name: "Home", exact: true }),
    ).toBeVisible();
  });
});

test.describe("as an employee without admin roles", () => {
  test.use({ storageState: USERS.employee.state });

  test("admin routes are refused", async ({ page }) => {
    for (const s of routed.filter((x) => x.shell === "admin" || x.shell === "wizard")) {
      await page.goto(samplePath(s.route));
      await expect(page.getByTestId("forbidden"), s.route).toBeVisible();
    }
  });

  test("the account menu has no admin console link", async ({ page }) => {
    await page.goto("/home");
    await page.getByRole("button", { name: /Account menu/ }).click();
    await expect(page.getByRole("menuitem", { name: "Admin console" })).toHaveCount(0);
  });

  test("the API answers 403 for admin-only data", async ({ page }) => {
    await page.goto("/home");
    const me = await page.request.get("/api/v1/me");
    expect(me.status()).toBe(200);
    const body = (await me.json()) as { can_open_admin: boolean; roles: Record<string, boolean> };
    expect(body.can_open_admin).toBe(false);
    expect(Object.values(body.roles).every((v) => v === false)).toBe(true);
    // Admin areas answer 403; the chatbot list holds only chatbots the caller administers.
    for (const path of [
      "/api/v1/admin/providers",
      "/api/v1/admin/sources",
      "/api/v1/admin/audit",
    ]) {
      expect((await page.request.get(path)).status(), path).toBe(403);
    }
    expect(await (await page.request.get("/api/v1/admin/chatbots")).json()).toEqual([]);
  });
});

test.describe("sign-out", () => {
  test("ends the session in Veyntora and Keycloak", async ({ browser }) => {
    // A fresh session, so the shared employee session used by other tests stays valid.
    const context = await browser.newContext();
    const page = await context.newPage();
    await signIn(page, USERS.employee);
    await page.getByRole("button", { name: /Account menu/ }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await page.waitForURL(/\/sign-in\?signed_out=1/);
    await expect(page.getByRole("status")).toHaveText("You are signed out.");
    await page.goto("/home");
    await expect(page).toHaveURL(/\/sign-in\?return_to=%2Fhome/);
    await context.close();
  });
});
