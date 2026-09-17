import { describe, expect, it, vi } from "vitest";
import { capabilities, incident } from "../../test/fixtures";
import { ApiClient, ApiProblem, retryable } from "./client";

describe("real HTTP client contract", () => {
  it("authenticates via C0 and sends bearer only in headers; encodes resource IDs", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ access_token: "test-token" }))
      .mockResolvedValueOnce(Response.json(incident));
    vi.stubGlobal("fetch", fetcher);
    const client = new ApiClient();
    await client.authenticate(capabilities);
    await client.incident("id/escape");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/auth/test-session");
    expect(fetcher.mock.calls[1][0]).toBe("/api/v1/incidents/id%2Fescape");
    expect(fetcher.mock.calls[1][1].headers.get("Authorization")).toBe(
      "Bearer test-token",
    );
    expect(localStorage.length).toBe(0);
    expect(window.location.href).not.toContain("test-token");
  });
  it("production never falls back to test auth", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    await expect(
      new ApiClient().authenticate({
        ...capabilities,
        environment: "production",
      }),
    ).rejects.toBeInstanceOf(ApiProblem);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("uses initData only at the MAX authentication boundary", async () => {
    window.WebApp = { initData: "test-only-init" };
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json({ access_token: "test-token" }));
    vi.stubGlobal("fetch", fetcher);
    await new ApiClient().authenticate(capabilities);
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/auth/max");
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      init_data: "test-only-init",
    });
  });
  it("preserves HTTP error status even if an error body lies", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(Response.json({ status: 200 }, { status: 403 })),
    );
    await expect(new ApiClient().incident("id")).rejects.toMatchObject({
      problem: { status: 403 },
    });
  });
  it("handles a non-JSON proxy response safely", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("secret-proxy-output", { status: 503 }),
        ),
    );
    await expect(new ApiClient().incident("id")).rejects.toMatchObject({
      problem: { status: 503, detail: "Сервис временно недоступен." },
    });
  });
  it("forwards cancellation and releases aborted auth results", async () => {
    const controller = new AbortController();
    const fetcher = vi
      .fn()
      .mockImplementation(
        (_path, options) =>
          new Promise((_resolve, reject) =>
            options.signal.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            ),
          ),
      );
    vi.stubGlobal("fetch", fetcher);
    const pending = new ApiClient().incident("id", controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  });
  it("bounds requests with a timeout", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockImplementation(
            (_path, options) =>
              new Promise((_resolve, reject) =>
                options.signal.addEventListener("abort", () =>
                  reject(new DOMException("Aborted", "AbortError")),
                ),
              ),
          ),
      );
      const pending = expect(
        new ApiClient().incident("id"),
      ).rejects.toMatchObject({ name: "AbortError" });
      await vi.advanceTimersByTimeAsync(20000);
      await pending;
    } finally {
      vi.useRealTimers();
    }
  });
  it("uses real pagination parameters", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json({
          items: [],
          page: { offset: 100, limit: 100, total: 100 },
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    await new ApiClient().incidents("house", undefined, 100);
    expect(fetcher.mock.calls[0][0]).toBe(
      "/api/v1/houses/house/incidents?limit=100&offset=100",
    );
  });
  it("does not retry access denial or explicit nonretryable problems", () => {
    expect(retryable(new ApiProblem({ status: 403 } as never))).toBe(false);
    expect(
      retryable(new ApiProblem({ status: 503, retryable: false } as never)),
    ).toBe(false);
  });
});
