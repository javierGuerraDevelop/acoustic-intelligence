import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LatestDetection } from "@/components/LatestDetection";
import type { EventHistoryItem } from "@/types/contracts";

const mockItem: EventHistoryItem = {
  event: {
    schema_version: 1,
    event_id: "event-test-001",
    device_id: "laptop-test",
    stream_id: "stream-test",
    event_seq: 1,
    window_start_at: "2026-09-26T20:00:00Z",
    occurred_at: "2026-09-26T20:00:01Z",
    detected_at: "2026-09-26T20:00:02Z",
    label: "knock",
    model_score: 0.82,
    severity: "attention",
    action_id: "check_door",
    source: "fixture",
  },
  acknowledged_at: null,
};

describe("LatestDetection", () => {
  it("shows a knock detection", () => {
    render(
      <LatestDetection
        item={mockItem}
        isAcknowledging={false}
        speechEnabled={false}
        isGeneratingSpeech={false}
        isPlayingSpeech={false}
        onAcknowledge={() => {}}
        onSpeak={() => {}}
      />
    );

    expect(
      screen.getByText("Possible knocking")
    ).toBeInTheDocument();

    expect(
      screen.getByText("Check the door")
    ).toBeInTheDocument();

    expect(
      screen.getByText("Needs attention")
    ).toBeInTheDocument();

    expect(
      screen.getByText("Model score: 0.82")
    ).toBeInTheDocument();
  });

  it("calls acknowledge with the event id", async () => {
    const user = userEvent.setup();
    const onAcknowledge = vi.fn();

    render(
      <LatestDetection
        item={mockItem}
        isAcknowledging={false}
        speechEnabled={false}
        isGeneratingSpeech={false}
        isPlayingSpeech={false}
        onAcknowledge={onAcknowledge}
        onSpeak={() => {}}
      />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Acknowledge",
      })
    );

    expect(onAcknowledge).toHaveBeenCalledOnce();

    expect(onAcknowledge).toHaveBeenCalledWith(
      "event-test-001"
    );
  });

  it("disables Speak Alert when speech is disabled", () => {
    render(
      <LatestDetection
        item={mockItem}
        isAcknowledging={false}
        speechEnabled={false}
        isGeneratingSpeech={false}
        isPlayingSpeech={false}
        onAcknowledge={() => {}}
        onSpeak={() => {}}
      />
    );

    expect(
      screen.getByRole("button", {
        name: "Speak Alert",
      })
    ).toBeDisabled();
  });
});