import { test, expect } from "@playwright/test";

test.describe("Home page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("renders role selector heading", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("name input accepts text", async ({ page }) => {
    const input = page.getByRole("textbox");
    await input.fill("Alex");
    await expect(input).toHaveValue("Alex");
  });

  test("Start Learning navigates to /student with name", async ({ page }) => {
    await page.getByRole("textbox").fill("Alex");
    await page.getByRole("button", { name: /start learning/i }).click();
    await expect(page).toHaveURL(/\/student\?name=Alex/);
  });

  test("Monitor Sessions navigates to /teacher with name", async ({ page }) => {
    await page.getByRole("textbox").fill("Ms Jones");
    await page.getByRole("button", { name: /monitor sessions/i }).click();
    await expect(page).toHaveURL(/\/teacher\?name=Ms(\+|%20)Jones/);
  });

  test("empty name does not crash on navigation attempt", async ({ page }) => {
    // Either shows validation or navigates gracefully (no 500 error)
    await page.getByRole("button", { name: /start learning/i }).click();
    // Page should still be responsive — not a crash
    await expect(page).not.toHaveURL(/error/);
  });
});
