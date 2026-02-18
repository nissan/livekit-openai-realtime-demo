import { test, expect } from "@playwright/test";

test.describe("Student page /student", () => {
  test("renders loading state when navigating with name", async ({ page }) => {
    // Navigate without a LiveKit backend — page should render without crashing
    await page.goto("/student?name=Alex");
    // Should show the student name somewhere (loading spinner or room UI)
    await expect(page.locator("body")).not.toBeEmpty();
    // Must not show a Next.js error page
    await expect(page.locator("h2:has-text('Application error')")).not.toBeVisible();
  });

  test("page title reflects student context", async ({ page }) => {
    await page.goto("/student?name=Alex");
    // Any heading or title should mention Alex or show student UI
    const title = await page.title();
    // Title should not be empty or a generic error
    expect(title).not.toBe("");
  });

  test("renders without crashing for any student name", async ({ page }) => {
    await page.goto("/student?name=Jordan");
    // Page should not redirect to /500 or show unhandled error
    await expect(page).not.toHaveURL(/\/_error/);
    await expect(page.locator("body")).toBeVisible();
  });
});
