import type { DetectionEvent } from "@/types/contracts"

export const mockEvents: DetectionEvent[] = [
  {
    schema_version: 1,
    event_id: "event-001",
    device_id: "laptop-01",
    stream_id: "stream-01",
    event_seq: 1,

    window_start_at: "2026-09-26T19:30:00Z",
    occurred_at: "2026-09-26T19:30:01Z",
    detected_at: "2026-09-26T19:30:02Z",

    label: "knock",
    model_score: 0.82,
    severity: "attention",
    action_id: "check_door",
    source: "fixture",
  },
  {
    schema_version: 1,
    event_id: "event-002",
    device_id: "laptop-01",
    stream_id: "stream-01",
    event_seq: 2,

    window_start_at: "2026-09-26T19:34:00Z",
    occurred_at: "2026-09-26T19:34:01Z",
    detected_at: "2026-09-26T19:34:02Z",

    label: "doorbell",
    model_score: 0.91,
    severity: "attention",
    action_id: "check_door",
    source: "fixture",
  },
]