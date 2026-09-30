import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
import { createControlPlaneReader } from "./control-plane";
import { handleControlRequest } from "./control-route";

const origin = "https://control.example.test";
const headers = { authorization: "Bearer e30.e30.signature", origin: "https://web.example.test" };

function fetcher(value: unknown) {
  return vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(value)));
}

describe("Published proxy", () => {
  it("forwards only bounded GET filters with the user's JWT and no-store", async () => {
    const fetchImpl = fetcher({ items: [], next_cursor: null });
    const request = new Request(
      "https://web.example.test/api/control/publications?group=swing&type=swing_context&limit=20",
      { headers },
    );
    const response = await handleControlRequest(request, ["publications"], { origin, fetchImpl });
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(fetchImpl.mock.calls[0][0]).toBe(
      `${origin}/v1/publications?limit=20&group=swing&type=swing_context`,
    );
    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      method: "GET",
      cache: "no-store",
      headers: { Authorization: "Bearer e30.e30.signature" },
    });
  });

  it("rejects machine submission, unknown filters, and repeated query keys", async () => {
    const fetchImpl = fetcher({ items: [], next_cursor: null });
    const post = new Request("https://web.example.test/api/control/publications", {
      method: "POST",
      headers: { ...headers, "content-type": "application/json" },
      body: "{}",
    });
    expect((await handleControlRequest(post, ["publications"], { origin, fetchImpl })).status).toBe(
      404,
    );
    for (const query of ["unsafe=secret", "limit=1&limit=2", "type=not_a_type"]) {
      const request = new Request(`https://web.example.test/api/control/publications?${query}`, {
        headers,
      });
      expect(
        (await handleControlRequest(request, ["publications"], { origin, fetchImpl })).status,
      ).toBe(422);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reads coverage only for signed-in users and validates the cutover shape", async () => {
    const fetchImpl = fetcher({ cutover: null, overall_status: "not_started", owners: [] });
    const request = new Request("https://web.example.test/api/control/publications/coverage", {
      headers,
    });
    const response = await handleControlRequest(request, ["publications", "coverage"], {
      origin,
      fetchImpl,
    });
    expect(response.status).toBe(200);
    expect(fetchImpl.mock.calls[0][0]).toBe(`${origin}/v1/publications/coverage`);
    const noAuth = new Request("https://web.example.test/api/control/publications/coverage");
    expect(
      (await handleControlRequest(noAuth, ["publications", "coverage"], { origin, fetchImpl }))
        .status,
    ).toBe(401);
  });
});

it("rejects invalid detail IDs before contacting the backend", async () => {
  const fetchImpl = fetcher({});
  const reader = createControlPlaneReader({
    origin,
    getAccessToken: async () => "user-session-token",
    fetchImpl,
  });
  await expect(reader.getPublication("not-an-opaque-id")).rejects.toMatchObject({
    code: "validation",
  });
  expect(fetchImpl).not.toHaveBeenCalled();
});
