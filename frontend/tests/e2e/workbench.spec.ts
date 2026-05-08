import { test, expect } from "@playwright/test";

test.describe("Interview Copilot Workbench", () => {
  test.skip(
    !process.env.E2E_BASE_URL,
    "Set E2E_BASE_URL and run the frontend/backend locally to execute browser flows."
  );

  test("shows the dashboard shell", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByText("Workbench")).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload source" })).toBeVisible();
  });
});
