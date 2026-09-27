import { act, renderHook } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { useSystemState } from "@/hooks/useSystemState";
import { startStatePolling } from "@/services/pollState";
import type {
  DetectionEvent,
  Settings,
  StateResponse,
} from "@/types/contracts";

vi.mock("@/services/pollState", () => ({
  startStatePolling: vi.fn(),
}));

const mockedStartStatePolling =
  vi.mocked(startStatePolling);

type PollCallbacks = Parameters<
  typeof startStatePolling
>[0];

let callbacks: PollCallbacks;

const sampleEvent: DetectionEvent = {
  schema_version: 1,
  event_id: "event-test-001",
  device_id: "laptop-test",
  stream_id: "stream-test",
  event_seq: 1,
  window_start_at: "2026-09-26T20:00:00.000Z",
  occurred_at: "2026-09-26T20:00:02.000Z",
  detected_at: "2026-09-26T20:00:02.100Z",
  label: "knock",
  model_score: 0.8,
  severity: "info",
  action_id: "check_door",
  source: "microphone",
  processing: {
    model_id: "yamnet/1",
    rule_version: "demo-1",
    sample_rate_hz: 16000,
    window_ms: 2000,
    hop_ms: 1000,
    last_chunk_seq: 1,
    inference_ms: 100,
    capture_to_detection_ms: 100,
    rms_dbfs: -20,
    dropped_frames_total: 0,
  },
};

const sampleSettings: Settings = {
  schema_version: 1,
  revision: 1,
  capture_enabled: true,
  cloud_storage_enabled: false,
  analytics_enabled: false,
  speech_enabled: false,
  retention_days: 1,
  cooldown_seconds: 10,
  muted_until: null,
};

function createStateResponse(
  overrides: Partial<StateResponse> = {}
): StateResponse {
  return {
    schema_version: 1,
    instance_id: "instance-test",
    cursor: 1,
    reset_required: false,
    status: {
      capture: "running",
      model: "ready",
      cloud: "disabled",
      export_pending: 0,
      export_dropped: 0,
      audio_gaps: 0,
    },
    changes: [],
    ...overrides,
  };
}

describe("useSystemState", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockedStartStatePolling.mockImplementation(
      (options) => {
        callbacks = options;

        return () => {};
      }
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("increments eventVersion for event.created", () => {
    const { result } = renderHook(() =>
      useSystemState()
    );

    expect(result.current.eventVersion).toBe(0);

    act(() => {
      callbacks.onState(
        createStateResponse({
          changes: [
            {
              cursor: 1,
              type: "event.created",
              event_id: sampleEvent.event_id,
              data: { event: sampleEvent },
            },
          ],
        })
      );
    });

    expect(result.current.eventVersion).toBe(1);
  });

  it("increments eventVersion for event.acknowledged", () => {
    const { result } = renderHook(() =>
      useSystemState()
    );

    act(() => {
      callbacks.onState(
        createStateResponse({
          changes: [
            {
              cursor: 2,
              type: "event.acknowledged",
              event_id: sampleEvent.event_id,
              data: {
                event_id: sampleEvent.event_id,
                acknowledged_at: "2026-09-26T20:00:05.000Z",
              },
            },
          ],
        })
      );
    });

    expect(result.current.eventVersion).toBe(1);
  });

  it("increments eventVersion for history.cleared", () => {
    const { result } = renderHook(() =>
      useSystemState()
    );

    act(() => {
      callbacks.onState(
        createStateResponse({
          changes: [
            {
              cursor: 3,
              type: "history.cleared",
              data: { deletion_id: "deletion-1" },
            },
          ],
        })
      );
    });

    expect(result.current.eventVersion).toBe(1);
  });

  it("does not increment eventVersion for unrelated changes", () => {
    const { result } = renderHook(() =>
      useSystemState()
    );

    act(() => {
      callbacks.onState(
        createStateResponse({
          changes: [
            {
              cursor: 4,
              type: "settings.changed",
              data: { settings: sampleSettings },
            },
          ],
        })
      );
    });

    expect(result.current.eventVersion).toBe(0);
  });

  it("increments resetVersion once during a continuous reset condition", () => {
    const { result } = renderHook(() =>
      useSystemState()
    );

    act(() => {
      callbacks.onState(
        createStateResponse({
          reset_required: true,
        })
      );
    });

    expect(result.current.resetVersion).toBe(1);

    act(() => {
      callbacks.onState(
        createStateResponse({
          reset_required: true,
        })
      );
    });

    expect(result.current.resetVersion).toBe(1);
  });

  it("allows a later reset after the previous reset clears", () => {
    const { result } = renderHook(() =>
      useSystemState()
    );

    act(() => {
      callbacks.onState(
        createStateResponse({
          reset_required: true,
        })
      );
    });

    expect(result.current.resetVersion).toBe(1);

    act(() => {
      callbacks.onState(
        createStateResponse({
          reset_required: false,
        })
      );
    });

    act(() => {
      callbacks.onState(
        createStateResponse({
          reset_required: true,
        })
      );
    });

    expect(result.current.resetVersion).toBe(2);
  });

  it("reports disconnected after two seconds without any success", () => {
    vi.useFakeTimers();

    const { result } = renderHook(() =>
      useSystemState()
    );

    expect(result.current.isDisconnected).toBe(false);

    act(() => {
      vi.advanceTimersByTime(2600);
    });

    expect(result.current.isDisconnected).toBe(true);
  });

  it("stays connected while responses keep arriving", () => {
    vi.useFakeTimers();

    const { result } = renderHook(() =>
      useSystemState()
    );

    act(() => {
      callbacks.onState(createStateResponse());
    });

    act(() => {
      vi.advanceTimersByTime(1500);
    });

    act(() => {
      callbacks.onState(createStateResponse());
    });

    act(() => {
      vi.advanceTimersByTime(1500);
    });

    expect(result.current.isDisconnected).toBe(false);
  });
});
