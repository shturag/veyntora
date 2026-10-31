import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const USERS = {
  admin: {
    username: "admin",
    password: process.env.VEY_DEV_ADMIN_PASSWORD ?? "dev-admin",
    state: "e2e/.auth/admin.json",
  },
  employee: {
    username: "employee",
    password: process.env.VEY_DEV_EMPLOYEE_PASSWORD ?? "dev-employee",
    state: "e2e/.auth/employee.json",
  },
} as const;

/** Sign in through the real Keycloak login form. */
export async function signIn(
  page: Page,
  user: (typeof USERS)[keyof typeof USERS],
  returnTo = "/home",
) {
  await page.goto(`/sign-in?return_to=${encodeURIComponent(returnTo)}`);
  await page.getByRole("link", { name: "Sign in with company account" }).click();
  await page.locator("#username").fill(user.username);
  await page.locator("#password").fill(user.password);
  await page.locator("#kc-login").click();
  await page.waitForURL((url) => url.pathname === returnTo.split("?")[0]);
}

/** WCAG 2.2 AA checks with axe. */
export async function expectNoA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}
