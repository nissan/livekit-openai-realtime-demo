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
    // Default role is student, so button already reads "Start Learning →"
    await page.getByRole("textbox").fill("Alex");
    await page.getByRole("button", { name: /start learning/i }).click();
    await expect(page).toHaveURL(/\/student\?name=Alex/);
  });

  test("Monitor Sessions navigates to /teacher with name", async ({ page }) => {
    // Must switch to teacher role first — button label is role-dependent
    await page.getByRole("button", { name: /teacher/i }).click();
    await page.getByRole("textbox").fill("Ms Jones");
    await page.getByRole("button", { name: /monitor sessions/i }).click();
    await expect(page).toHaveURL(/\/teacher\?name=Ms(\+|%20)Jones/);
  });

  test("Start button is disabled when name is empty", async ({ page }) => {
    // Button is disabled when name is blank (disabled={!name.trim()})
    await expect(
      page.getByRole("button", { name: /start learning/i })
    ).toBeDisabled();
  });
});
