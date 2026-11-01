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
    // Auto, Fast and Agent can all be the default.
    await expect(page.getByLabel("Default mode").locator("option")).toHaveText([
      "Auto",
      "Fast",
      "Agent",
    ]);

    // Own keys only where an assistant's data rule allows them.
    const keys = page.getByRole("region", { name: "My API keys" });
    if (await keys.getByText("Not enabled").count()) {
      await expect(keys.getByRole("button", { name: "+ Add key" })).toBeDisabled();
    }

    const privacy = page.getByRole("region", { name: "Privacy and data" });
    const download = page.waitForEvent("download");
    await privacy.getByRole("link", { name: "Export my data" }).click();
    expect((await download).suggestedFilename()).toBe("my-veyntora-data.zip");
    const keep = privacy.getByLabel(/Keep chat history/);
    await keep.uncheck();
    await expect(privacy.getByText("Chats will be deleted after a day.")).toBeVisible();
    await keep.check();
    await expect(privacy.getByText("Chat history is kept.")).toBeVisible();
    await privacy.getByRole("button", { name: "Delete all chats" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete all your chats?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expectNoA11yViolations(page);
  });
});
