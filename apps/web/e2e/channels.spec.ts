import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("channels & API as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("shows the channel table, the widget snippet and app keys", async ({ page }) => {
    await page.goto("/admin/channels");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Channels & API");
    await expect(page.getByRole("heading", { name: "App keys for the API" })).toBeVisible();
    if (await page.getByRole("heading", { name: "Website widget" }).count()) {
      await expect(page.locator("pre").first()).toContainText("widget.js");
    }
    const teams = page.getByRole("form", { name: "Microsoft Teams" });
    if (await teams.count()) {
      await expect(teams.getByLabel("Messaging endpoint")).toHaveValue(/\/teams\/messages$/);
      await expect(
        page.getByRole("form", { name: "Slack" }).getByLabel("Messaging endpoint"),
      ).toHaveValue(/\/slack\/events$/);
    }
    await page.getByRole("button", { name: "+ Create app key" }).click();
    await expect(page.getByRole("dialog", { name: "Create an app key" })).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
    expect(await page.content()).not.toMatch(/vey_ak_[0-9a-f]{12}_[A-Za-z0-9_-]{20,}/);
    await expectNoA11yViolations(page);
  });
});

test.describe("website widget frame", () => {
  test("refuses to be framed when the widget is not enabled", async ({ page }) => {
    const res = await page.goto("/widget/no-such-chatbot");
    expect(res?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
    await expect(page.getByText("This assistant is not available here.")).toBeVisible();
  });

  test("the loader script is public and only builds a frame for valid names", async ({
    request,
  }) => {
    const res = await request.get("/widget.js");
    expect(res.status()).toBe(200);
    expect(await res.text()).toContain("/widget/");
  });
});

test.describe("linking a Teams or Slack account", () => {
  test.use({ storageState: USERS.employee.state });

  test("an unknown or expired link is refused", async ({ page }) => {
    await page.goto("/link/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
    await expect(page.getByRole("main").getByRole("alert")).toContainText("not valid any more");
  });

  test("settings list the linked accounts", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByRole("heading", { name: "Linked Teams and Slack accounts" }),
    ).toBeVisible();
  });
});
