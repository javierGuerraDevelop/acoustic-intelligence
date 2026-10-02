import {
  act,
  renderHook,
} from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { useActivitySummary } from "@/hooks/useActivitySummary";
import {
  getJob,
  requestSummary,
} from "@/services/api";
import type {
  Job,
  SummaryResult,
} from "@/types/contracts";

vi.mock("@/services/api", () => ({
  requestSummary: vi.fn(),
  getJob: vi.fn(),
}));

const mockedRequestSummary = vi.mocked(requestSummary);
const mockedGetJob = vi.mocked(getJob);

const summary: SummaryResult = {
  text: "Two possible knocking detections were counted.",
  event_count: 2,
  counts: { knock: 2 },
  since: "2026-10-02T12:00:00.000Z",
  through: "2026-10-02T12:25:00.000Z",
  generated_at: "2026-10-02T12:30:00.000Z",
  model: "llama3.3-70b",
  query_id: "query-1",
};

function pendingJob(): Job {
  return {
    schema_version: 1,
    job_id: "job-1",
    kind: "summary",
    state: "pending",
    updated_at: "2026-10-02T12:30:00.000Z",
    result: null,
    error: null,
  };
}

describe("useActivitySummary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls until the job completes and stores the summary", async () => {
    mockedRequestSummary.mockResolvedValue(
      pendingJob()
    );
    mockedGetJob.mockResolvedValue({
      ...pendingJob(),
      state: "complete",
      result: summary,
    });

    const { result } = renderHook(() =>
      useActivitySummary()
    );

    await act(async () => {
      const generation =
        result.current.generateSummary();
      await vi.advanceTimersByTimeAsync(1000);
      await generation;
    });

    expect(mockedGetJob).toHaveBeenCalledWith(
      "job-1"
    );
    expect(result.current.summary).toEqual(summary);
    expect(result.current.lastGeneratedAt).toBeInstanceOf(
      Date
    );
    expect(result.current.error).toBeNull();
    expect(result.current.isGenerating).toBe(false);
  });

  it("reports a failed job", async () => {
    mockedRequestSummary.mockResolvedValue({
      ...pendingJob(),
      state: "failed",
      error: {
        code: "TIMEOUT",
        retryable: true,
        message: "Snowflake analytics request failed.",
      },
    });

    const { result } = renderHook(() =>
      useActivitySummary()
    );

    await act(async () => {
      await result.current.generateSummary();
    });

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.summary).toBeNull();
  });

  it("ignores malformed job results", async () => {
    mockedRequestSummary.mockResolvedValue({
      ...pendingJob(),
      state: "complete",
      result: { unexpected: true },
    });

    const { result } = renderHook(() =>
      useActivitySummary()
    );

    await act(async () => {
      await result.current.generateSummary();
    });

    expect(result.current.summary).toBeNull();
    expect(result.current.lastGeneratedAt).toBeInstanceOf(
      Date
    );
    expect(result.current.error).toBeNull();
  });

  it("surfaces request failures", async () => {
    mockedRequestSummary.mockRejectedValue(
      new Error("network down")
    );

    const { result } = renderHook(() =>
      useActivitySummary()
    );

    await act(async () => {
      await result.current.generateSummary();
    });

    expect(result.current.error?.message).toBe(
      "network down"
    );
  });
});
