import { test, expect } from "@playwright/test";

test.describe("Error Boundary UI", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/test-error-boundary");
  });

  test("shows 'Component loaded successfully' before crash", async ({
    page,
  }) => {
    await expect(page.getByText("Component loaded successfully")).toBeVisible();
  });

  test("shows fallback UI after crash", async ({ page }) => {
    await page.getByRole("button", { name: /trigger error/i }).click();
    await expect(
      page.getByText(/something went wrong/i)
    ).toBeVisible();
    await expect(
      page.getByText(/Test crash: intentional render error/)
    ).toBeVisible();
  });

  test("Try Again button resets the boundary", async ({ page }) => {
    await page.getByRole("button", { name: /trigger error/i }).click();
    await expect(page.getByText(/something went wrong/i)).toBeVisible();
    await page.getByRole("button", { name: /try again/i }).click();
    await expect(page.getByText("Component loaded successfully")).toBeVisible();
  });

  test("boundary triggers POST to /api/log-error on crash", async ({
    page,
  }) => {
    let capturedBody: Record<string, unknown> | null = null;

    await page.route("/api/log-error", async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      capturedBody = body;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ logged: true }),
      });
    });

    await page.getByRole("button", { name: /trigger error/i }).click();
    await expect(page.getByText(/something went wrong/i)).toBeVisible();

    expect(capturedBody).not.toBeNull();
    expect(capturedBody!.error).toBe("Test crash: intentional render error");
    expect(capturedBody!.context).toBe("test-page");
    expect(typeof capturedBody!.timestamp).toBe("string");
  });
});

test.describe("/api/log-error endpoint", () => {
  test("returns 200 and { logged: true } for valid POST body", async ({
    request,
  }) => {
    const response = await request.post("/api/log-error", {
      data: {
        error: "test error message",
        errorName: "Error",
        context: "test-suite",
        timestamp: new Date().toISOString(),
      },
    });
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body).toEqual({ logged: true });
  });

  test("returns 400 when error field is missing", async ({ request }) => {
    const response = await request.post("/api/log-error", {
      data: { context: "test-suite" },
    });
    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body).toHaveProperty("error");
  });

  test("returns 400 for non-JSON body", async ({ request }) => {
    const response = await request.post("/api/log-error", {
      headers: { "Content-Type": "text/plain" },
      data: "not json",
    });
    expect([400]).toContain(response.status());
  });
});
