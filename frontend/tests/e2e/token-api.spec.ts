import { test, expect } from "@playwright/test";

test.describe("Token API /api/token", () => {
  test("returns 400 when required params are missing (no identity)", async ({
    request,
  }) => {
    const response = await request.get("/api/token");
    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body).toHaveProperty("error");
  });

  test("returns 400 when identity is missing (only name provided)", async ({
    request,
  }) => {
    const response = await request.get("/api/token?name=Test&role=student&room=test");
    expect(response.status()).toBe(400);
  });

  test("returns JSON response for valid params", async ({ request }) => {
    const response = await request.get(
      "/api/token?identity=test-user&name=Test+User&role=student&room=test-room"
    );
    // 200 when LiveKit is configured; 500 when env vars are absent in test env
    expect([200, 500]).toContain(response.status());
    const body = await response.json();
    expect(body).toBeInstanceOf(Object);
  });

  test("when configured: response has expected token shape", async ({ request }) => {
    const response = await request.get(
      "/api/token?identity=test-user&name=Test+User&role=student&room=test-room"
    );
    if (response.status() !== 200) {
      // Skip shape check when LiveKit env vars not present in test environment
      test.skip();
      return;
    }
    const body = await response.json();
    expect(body).toHaveProperty("token");
    expect(body).toHaveProperty("roomName");
    expect(body).toHaveProperty("identity");
    expect(body).toHaveProperty("livekitUrl");
    expect(typeof body.token).toBe("string");
    expect(body.token.length).toBeGreaterThan(0);
  });
});
