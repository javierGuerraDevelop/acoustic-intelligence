import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

// The live suite imports a fresh module instance with the mock flag
// explicitly off, so an exported VITE_USE_MOCK_API in the developer's
// shell cannot change what these tests exercise.
let api: typeof import("@/services/api");

const fetchMock = vi.fn();

function jsonResponse(
  body: unknown,
  { ok = true, status = 200 } = {}
): Response {
  return {
    ok,
    status,
    json: async () => body,
    blob: async () => new Blob([JSON.stringify(body)]),
  } as unknown as Response;
}

beforeAll(async () => {
  vi.stubEnv("VITE_USE_MOCK_API", "false");
  vi.resetModules();
  api = await import("@/services/api");
});

afterAll(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("live API client", () => {
  it("fetches system state with cursor and instance", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ cursor: 3 })
    );

    const result = await api.getSystemState({
      after: 2,
      instanceId: "instance-1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/state?after=2&instance_id=instance-1"
    );
    expect(result).toEqual({ cursor: 3 });
  });

  it("omits the state query string when no cursor is known", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));

    await api.getSystemState();

    expect(fetchMock).toHaveBeenCalledWith("/v1/state");
  });

  it("rejects failed state requests with the status", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({}, { ok: false, status: 503 })
    );

    await expect(api.getSystemState()).rejects.toThrow(
      "Failed to fetch system state: 503"
    );
  });

  it("posts a summary request with the canonical body", async () => {
    const job = { job_id: "job-1", state: "pending" };
    fetchMock.mockResolvedValue(jsonResponse(job));

    const result = await api.requestSummary();

    expect(result).toEqual(job);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/summary");
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({
      "Content-Type": "application/json",
    });

    const body = JSON.parse(options.body);
    expect(body.schema_version).toBe(1);
    expect(body.lookback_minutes).toBe(30);
    expect(body.request_id).toMatch(
      /^[0-9a-f-]{36}$/
    );
  });

  it("polls a job by id", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-1", state: "complete" })
    );

    const job = await api.getJob("job-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/jobs/job-1"
    );
    expect(job.state).toBe("complete");
  });

  it("rejects an unknown job", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({}, { ok: false, status: 404 })
    );

    await expect(api.getJob("missing")).rejects.toThrow(
      "Failed to fetch job: 404"
    );
  });

  it("posts history deletion with the all_history scope", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ job_id: "job-2" })
    );

    await api.deleteHistory();

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/privacy/delete");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body).scope).toBe(
      "all_history"
    );
  });

  it("lists events with paging parameters", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], next_cursor: null })
    );

    await api.getEvents(25, "cursor-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/events?limit=25&before=cursor-1"
    );
  });

  it("patches settings", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ revision: 2 })
    );

    const result = await api.updateSettings({
      schema_version: 1,
      request_id: "request-1",
      expected_revision: 1,
      changes: { capture_enabled: true },
    });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/v1/settings");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(options.body).expected_revision).toBe(
      1
    );
    expect(result).toEqual({ revision: 2 });
  });
});

describe("mock API mode", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("returns a contract-valid summary without network calls", async () => {
    vi.stubEnv("VITE_USE_MOCK_API", "true");
    vi.resetModules();
    const mockApi = await import("@/services/api");

    vi.useFakeTimers();
    const generation = mockApi.requestSummary();
    await vi.advanceTimersByTimeAsync(500);
    const job = await generation;

    expect(job.state).toBe("complete");
    expect(job.result).toMatchObject({
      event_count: 2,
      counts: { knock: 2 },
      model: "llama3.3-70b",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("deletes history without network calls", async () => {
    vi.stubEnv("VITE_USE_MOCK_API", "true");
    vi.resetModules();
    const mockApi = await import("@/services/api");

    vi.useFakeTimers();
    const deletion = mockApi.deleteHistory();
    await vi.advanceTimersByTimeAsync(500);
    const job = await deletion;

    expect(job.result).toMatchObject({
      local: "complete",
      atlas: "complete",
      snowflake: "complete",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
