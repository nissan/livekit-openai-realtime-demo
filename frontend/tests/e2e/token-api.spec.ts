import { test, expect } from "@playwright/test";

test.describe("Token API /api/token", () => {
  test("returns 200 with all required params", async ({ request }) => {
    const response = await request.get(
      "/api/token?identity=test-user&name=Test+User&role=student&room=test-room"
    );
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body).toHaveProperty("token");
    expect(body).toHaveProperty("roomName");
    expect(body).toHaveProperty("identity");
    expect(body).toHaveProperty("livekitUrl");
    expect(typeof body.token).toBe("string");
    expect(body.token.length).toBeGreaterThan(0);
  });

  test("returns expected roomName from params", async ({ request }) => {
    const response = await request.get(
      "/api/token?identity=test-user&name=Test&role=student&room=my-room"
    );
    const body = await response.json();
    expect(body.roomName).toContain("my-room");
  });

  test("returns 400 when required params are missing", async ({ request }) => {
    const response = await request.get("/api/token");
    expect(response.status()).toBe(400);
  });

  test("returns 400 when identity is missing", async ({ request }) => {
    const response = await request.get("/api/token?name=Test&role=student&room=test");
    expect(response.status()).toBe(400);
  });
});
