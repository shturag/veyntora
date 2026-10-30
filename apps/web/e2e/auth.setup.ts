import { test as setup } from "@playwright/test";

import { signIn, USERS } from "./fixtures";

for (const [name, user] of Object.entries(USERS)) {
  setup(`sign in as ${name}`, async ({ page }) => {
    await signIn(page, user);
    await page.context().storageState({ path: user.state });
  });
}
