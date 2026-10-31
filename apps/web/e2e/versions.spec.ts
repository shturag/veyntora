import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("versions and roll-out as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("history, the guard, and a canary that is started and stopped", async ({ page }) => {
    await page.goto("/admin/chatbots");
    const hrefs = await page
      .locator("a")
      .evaluateAll((links) =>
        links
          .map((a) => a.getAttribute("href") ?? "")
          .filter((h) => /^\/admin\/chatbots\/[0-9a-f-]{36}$/.test(h)),
      );
    test.skip(hrefs.length === 0, "no chatbot on this stack yet");
    await page.goto(`${hrefs[0]}/versions`);
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
    await expect(page.getByRole("form", { name: "Automatic rollback" })).toBeVisible();
    await expectNoA11yViolations(page);
    const start = page.getByRole("button", { name: "Start canary with the draft" });
    test.skip((await start.count()) === 0 || !(await start.isEnabled()), "nothing live to compare with");
    await start.click();
    await page.getByRole("dialog").getByRole("button", { name: "Start canary" }).click();
    await expect(page.getByRole("dialog").getByText("Canary at 10%.")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.reload();
    await expect(page.getByText(/canary · 10%/)).toBeVisible();
    await page.getByRole("button", { name: "Stop canary" }).click();
    await page.getByRole("dialog").getByLabel("Reason").fill("e2e check");
    await page.getByRole("dialog").getByRole("button", { name: "Stop canary" }).click();
    await expect(page.getByRole("dialog").getByText(/Canary stopped/)).toBeVisible();
  });
});
