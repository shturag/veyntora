import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("chatbots as a platform admin", () => {
  test.use({ storageState: USERS.admin.state });

  test("lists chatbots and opens overview, knowledge and access", async ({ page }) => {
    await page.goto("/admin/chatbots");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Chatbots");
    await expectNoA11yViolations(page);
    const first = page.getByRole("main").getByRole("listitem").getByRole("link").first();
    if ((await first.count()) === 0) test.skip(true, "no chatbots in this database");
    await first.click();
    const tabs = page.getByRole("navigation", { name: "Chatbot" });
    await expect(tabs.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expectNoA11yViolations(page);
    await tabs.getByRole("link", { name: "Knowledge" }).click();
    await expect(
      page.getByRole("heading", { name: "Knowledge this chatbot answers from" }),
    ).toBeVisible();
    await expectNoA11yViolations(page);
    await tabs.getByRole("link", { name: "Access" }).click();
    await expect(page.getByRole("heading", { name: "Who can use this chatbot" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Preview as a person" })).toBeVisible();
    await expectNoA11yViolations(page);
  });

  test("the wizard opens later steps only once the chatbot exists", async ({ page }) => {
    await page.goto("/admin/chatbots/new");
    await expect(page.getByRole("form", { name: "Basics" })).toBeVisible();
    const steps = page.getByRole("list", { name: "Steps" });
    await expect(steps.getByRole("link")).toHaveCount(1);
    await expect(steps.getByText("2 Knowledge")).toHaveAttribute("aria-disabled", "true");
    await expectNoA11yViolations(page);
  });
});
