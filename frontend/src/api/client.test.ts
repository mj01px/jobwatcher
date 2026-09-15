import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, request } from "./client";

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function mockFetch(...responses: Response[]) {
  const fetchMock = vi.fn<typeof fetch>();
  for (const response of responses) fetchMock.mockResolvedValueOnce(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function headersOf(call: Parameters<typeof fetch> | undefined): Record<string, string> {
  return (call?.[1]?.headers ?? {}) as Record<string, string>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("unwraps data and meta from the envelope", async () => {
    const fetchMock = mockFetch(
      jsonResponse({
        data: [{ id: 1 }],
        error: null,
        meta: { requestId: "abc", page: 2, perPage: 20, total: 21, totalPages: 2 },
      }),
    );

    const result = await api.jobs("highlighted", 2);

    expect(result.data).toEqual([{ id: 1 }]);
    expect(result.meta).toMatchObject({ requestId: "abc", page: 2, totalPages: 2 });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/jobs?view=highlighted&page=2");
  });

  it("throws a typed ApiError with code, details and request id", async () => {
    document.cookie = "csrftoken=t; path=/";
    mockFetch(
      jsonResponse(
        {
          data: null,
          error: {
            code: "VALIDATION_ERROR",
            message: "Invalid source",
            details: [{ field: "target", issue: "Must be an InHire career page" }],
          },
          meta: { requestId: "req-1" },
        },
        400,
      ),
    );

    const error = await api
      .createSource({ kind: "inhire", name: "x", target: "https://example.com" })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "VALIDATION_ERROR",
      status: 400,
      requestId: "req-1",
      details: [{ field: "target", issue: "Must be an InHire career page" }],
    });
  });

  it("sends the CSRF token from the cookie on unsafe methods", async () => {
    document.cookie = "csrftoken=token-123; path=/";
    const fetchMock = mockFetch(jsonResponse({ data: { id: 7 }, error: null, meta: { requestId: "r" } }));

    await api.archiveJob(7, { reason: "remote" });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/jobs/7/archive");
    expect(init?.method).toBe("POST");
    expect(headersOf(fetchMock.mock.calls[0])["X-CSRFToken"]).toBe("token-123");
    expect(JSON.parse(String(init?.body))).toEqual({ reason: "remote", note: "" });
  });

  it("does not send a CSRF header on GET", async () => {
    document.cookie = "csrftoken=token-123; path=/";
    const fetchMock = mockFetch(
      jsonResponse({ data: { groups: {}, minScore: 20, isDefault: true }, error: null, meta: { requestId: "r" } }),
    );

    await api.scoring();

    expect(headersOf(fetchMock.mock.calls[0])["X-CSRFToken"]).toBeUndefined();
  });

  it("bootstraps the CSRF cookie through /status when it is missing", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input).endsWith("/status")) {
        document.cookie = "csrftoken=fresh; path=/";
        return jsonResponse({ data: {}, error: null, meta: { requestId: "s" } });
      }
      return jsonResponse({ data: null, error: null, meta: { requestId: "c" } }, 202);
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.startCheck();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/v1/status");
    expect(headersOf(fetchMock.mock.calls[1])["X-CSRFToken"]).toBe("fresh");
  });

  it("returns null data for 204 responses", async () => {
    document.cookie = "csrftoken=t; path=/";
    mockFetch(new Response(null, { status: 204, headers: { "X-Request-ID": "gone" } }));

    const result = await api.deleteSource(3);

    expect(result.data).toBeNull();
    expect(result.meta.requestId).toBe("gone");
  });

  it("wraps network failures as NETWORK_ERROR", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(request("GET", "/overview")).rejects.toMatchObject({ code: "NETWORK_ERROR", status: 0 });
  });

  it("rejects non envelope bodies", async () => {
    mockFetch(new Response("<html>bad gateway</html>", { status: 502 }));

    await expect(request("GET", "/overview")).rejects.toMatchObject({ code: "INTERNAL_ERROR", status: 502 });
  });
});

describe("v2 endpoints", () => {
  const ok = (data: unknown, status = 200) => jsonResponse({ data, error: null, meta: { requestId: "r" } }, status);

  function call(fetchMock: ReturnType<typeof mockFetch>, index = 0) {
    const [url, init] = fetchMock.mock.calls[index] ?? [];
    return { url: String(url), method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
  }

  it("creates an application with the requested status", async () => {
    document.cookie = "csrftoken=t; path=/";
    const fetchMock = mockFetch(ok({ id: 9, status: "interest" }, 201));

    const result = await api.createApplication(42, "interest");

    expect(result.data).toMatchObject({ id: 9 });
    expect(call(fetchMock)).toEqual({ url: "/api/v1/jobs/42/application", method: "POST", body: { status: "interest" } });
  });

  it("reads the board and the closed list", async () => {
    const fetchMock = mockFetch(ok({ columns: [], overdue: [], counts: {} }), ok([]));

    await api.board();
    await api.closedApplications();

    expect(call(fetchMock, 0)).toMatchObject({ url: "/api/v1/applications/board", method: "GET" });
    expect(call(fetchMock, 1)).toMatchObject({ url: "/api/v1/applications/closed", method: "GET" });
  });

  it("patches an application and deletes it with a 204", async () => {
    document.cookie = "csrftoken=t; path=/";
    const fetchMock = mockFetch(ok({ id: 5 }), new Response(null, { status: 204 }));

    await api.updateApplication(5, { status: "interview", nextStepOn: null, hasReferral: true });
    const removed = await api.deleteApplication(5);

    expect(call(fetchMock, 0)).toEqual({
      url: "/api/v1/applications/5",
      method: "PATCH",
      body: { status: "interview", nextStepOn: null, hasReferral: true },
    });
    expect(call(fetchMock, 1)).toMatchObject({ url: "/api/v1/applications/5", method: "DELETE" });
    expect(removed.data).toBeNull();
  });

  it("manages interactions under their application", async () => {
    document.cookie = "csrftoken=t; path=/";
    const fetchMock = mockFetch(ok({ id: 1 }, 201), ok({ id: 1 }), new Response(null, { status: 204 }));

    await api.createInteraction(5, { date: "2026-09-14", title: "Call", detail: "" });
    await api.updateInteraction(1, { title: "Recruiter call" });
    await api.deleteInteraction(1);

    expect(call(fetchMock, 0)).toEqual({
      url: "/api/v1/applications/5/interactions",
      method: "POST",
      body: { date: "2026-09-14", title: "Call", detail: "" },
    });
    expect(call(fetchMock, 1)).toEqual({ url: "/api/v1/interactions/1", method: "PATCH", body: { title: "Recruiter call" } });
    expect(call(fetchMock, 2)).toMatchObject({ url: "/api/v1/interactions/1", method: "DELETE" });
  });

  it("surfaces the cover letter error codes", async () => {
    document.cookie = "csrftoken=t; path=/";
    mockFetch(
      jsonResponse(
        { data: null, error: { code: "GEMINI_NOT_CONFIGURED", message: "No key" }, meta: { requestId: "p" } },
        503,
      ),
    );

    await expect(api.generatePitch(42, "")).rejects.toMatchObject({ code: "GEMINI_NOT_CONFIGURED", status: 503 });
  });

  it("resets the scoring profile with null groups and saves secrets write only", async () => {
    document.cookie = "csrftoken=t; path=/";
    const fetchMock = mockFetch(
      ok({ groups: {}, minScore: 15, stackGroups: ["core", "adjacent"], isDefault: true }),
      ok({ geminiConfigured: true, githubConfigured: false }),
    );

    await api.saveScoring({ groups: null, minScore: 15, stackGroups: ["core", "adjacent"] });
    const secrets = await api.saveSecrets({ geminiApiKey: "k" });

    expect(call(fetchMock, 0)).toEqual({ url: "/api/v1/settings/scoring", method: "PUT", body: { groups: null, minScore: 15, stackGroups: ["core", "adjacent"] } });
    expect(call(fetchMock, 1)).toEqual({ url: "/api/v1/settings/secrets", method: "PUT", body: { geminiApiKey: "k" } });
    expect(secrets.data).toEqual({ geminiConfigured: true, githubConfigured: false });
  });
});
