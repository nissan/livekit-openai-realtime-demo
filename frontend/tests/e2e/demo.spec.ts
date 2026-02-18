import { test, expect } from "@playwright/test";

test.describe("Demo walkthrough /demo", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/demo");
  });

  test("renders without crashing", async ({ page }) => {
    await expect(page.locator("body")).toBeVisible();
    await expect(page.locator("h2:has-text('Application error')")).not.toBeVisible();
  });

  test("shows Testing Walkthrough heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /testing walkthrough/i })
    ).toBeVisible();
  });

  test("all 4 scenario sections are visible", async ({ page }) => {
    await expect(page.getByText(/scenario 1/i)).toBeVisible();
    await expect(page.getByText(/scenario 2/i)).toBeVisible();
    await expect(page.getByText(/scenario 3/i)).toBeVisible();
    await expect(page.getByText(/scenario 4/i)).toBeVisible();
  });

  test("progress tracker shows 0 / N completed initially", async ({ page }) => {
    // Clear localStorage to ensure clean state
    await page.evaluate(() => localStorage.removeItem("demo-walkthrough-progress"));
    await page.reload();
    await expect(page.getByText(/0\s*\/\s*\d+\s*completed/i)).toBeVisible();
  });

  test("checkboxes are clickable and update progress", async ({ page }) => {
    // Clear state first
    await page.evaluate(() => localStorage.removeItem("demo-walkthrough-progress"));
    await page.reload();

    const firstCheckbox = page.locator('input[type="checkbox"]').first();
    await firstCheckbox.check();
    await expect(firstCheckbox).toBeChecked();

    // Progress counter should advance
    await expect(page.getByText(/1\s*\/\s*\d+\s*completed/i)).toBeVisible();
  });

  test("progress persists after page reload", async ({ page }) => {
    await page.evaluate(() => localStorage.removeItem("demo-walkthrough-progress"));
    await page.reload();

    await page.locator('input[type="checkbox"]').first().check();
    await page.reload();

    // Checkbox should still be checked
    await expect(page.locator('input[type="checkbox"]').first()).toBeChecked();
  });

  test("Open Student Session link is present", async ({ page }) => {
    await expect(
      page.getByRole("link", { name: /open student session/i })
    ).toBeVisible();
  });

  test("Open Teacher Portal link is present", async ({ page }) => {
    await expect(
      page.getByRole("link", { name: /open teacher portal/i })
    ).toBeVisible();
  });

  test("Langfuse analysis section is visible", async ({ page }) => {
    await expect(page.getByText(/langfuse/i)).toBeVisible();
  });

  test("reset progress button clears checkboxes", async ({ page }) => {
    // Check one item first
    await page.locator('input[type="checkbox"]').first().check();

    // Reset
    await page.getByRole("button", { name: /reset progress/i }).click();

    // All checkboxes should be unchecked
    const checkboxes = page.locator('input[type="checkbox"]');
    const count = await checkboxes.count();
    for (let i = 0; i < count; i++) {
      await expect(checkboxes.nth(i)).not.toBeChecked();
    }
  });
});
