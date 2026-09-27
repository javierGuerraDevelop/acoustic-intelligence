import { act, renderHook } from "@testing-library/react";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { useSystemState } from "@/hooks/useSystemState";
import { startStatePolling } from "@/services/pollState";
import type { StateResponse } from "@/types/contracts";

vi.mock("@/services/pollState", () => ({
  startStatePolling: vi.fn(),
}));

const mockedStartStatePolling =
  vi.mocked(startStatePolling);

type PollCallbacks = Parameters<
  typeof startStatePolling
>[0];

let callbacks: PollCallbacks;

function createStateResponse(
  overrides: Partial<StateResponse> = {}
): StateResponse {
  return {
    instance_id: "instance-test",
    cursor: 1,
    reset_required: false,
    state: {
      capture: "running",
      model: "ready",
      cloud: "disabled",
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
              type: "event.created",
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
              type: "event.acknowledged",
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
              type: "history.cleared",
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
              type: "settings.changed",
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
});