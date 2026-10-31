import { expect, test } from "@playwright/test";

import { expectNoA11yViolations, USERS } from "./fixtures";

test.describe("settings as an employee", () => {
  test.use({ storageState: USERS.employee.state });

  test("saves answer preferences and keeps keys and privacy honest", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");

    const answers = page.getByRole("form", { name: "Answers" });
    const length = answers.getByLabel("Answer length");
    const original = await length.inputValue();
    await length.selectOption(original === "short" ? "detailed" : "short");
    await answers.getByRole("button", { name: "Save" }).click();
    await expect(answers.getByRole("status")).toHaveText("Saved.");
    await page.reload();
    await expect(page.getByLabel("Answer length")).not.toHaveValue(original);
    await page.getByLabel("Answer length").selectOption(original);
    await page.getByRole("form", { name: "Answers" }).getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("form", { name: "Answers" }).getByRole("status")).toHaveText(
      "Saved.",
    );
    // Modes arrive with the agent.
    await expect(page.getByLabel("Default mode")).toBeDisabled();

    // Own keys only where an assistant's data rule allows them.
    const keys = page.getByRole("region", { name: "My API keys" });
    if (await keys.getByText("Not enabled").count()) {
      await expect(keys.getByRole("button", { name: "+ Add key" })).toBeDisabled();
    }

    const privacy = page.getByRole("region", { name: "Privacy and data" });
    await expect(privacy.getByRole("button", { name: "Export my data" })).toBeDisabled();
    await privacy.getByRole("button", { name: "Delete all chats" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete all your chats?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expectNoA11yViolations(page);
  });
});
