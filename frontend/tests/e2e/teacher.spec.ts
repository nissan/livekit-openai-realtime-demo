import { test, expect } from "@playwright/test";

test.describe("Teacher portal /teacher", () => {
  test("renders Teacher Portal heading", async ({ page }) => {
    await page.goto("/teacher?name=Ms.+Jones");
    await expect(
      page.getByRole("heading", { name: /teacher portal/i })
    ).toBeVisible();
  });

  test("renders escalation monitoring panel", async ({ page }) => {
    await page.goto("/teacher?name=Ms.+Jones");
    // Should show monitoring state (empty or active)
    const monitoringText = page.getByText(/monitoring/i);
    await expect(monitoringText).toBeVisible();
  });

  test("renders without crashing when Supabase is unavailable", async ({ page }) => {
    await page.goto("/teacher?name=TestTeacher");
    // No Supabase in test env — page should gracefully handle missing data
    await expect(page.locator("h2:has-text('Application error')")).not.toBeVisible();
    await expect(page.locator("body")).toBeVisible();
  });

  test("teacher name appears on the page", async ({ page }) => {
    await page.goto("/teacher?name=Ms.+Jones");
    await expect(page.getByText(/Ms\.?\s*Jones/i)).toBeVisible();
  });
});
