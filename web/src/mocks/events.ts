import type { DetectionEvent } from "@/types/contracts"

export const mockEvents: DetectionEvent[] = [
  {
    schema_version: 1,
    event_id: "event-001",
    device_id: "laptop-01",
    stream_id: "stream-01",
    event_seq: 1,

    window_start_at: "2026-09-26T19:30:00.000Z",
    occurred_at: "2026-09-26T19:30:02.000Z",
    detected_at: "2026-09-26T19:30:02.120Z",

    label: "knock",
    model_score: 0.82,
    severity: "info",
    action_id: "check_door",
    source: "fixture",

    processing: {
      model_id: "yamnet/1",
      rule_version: "demo-1",
      sample_rate_hz: 16000,
      window_ms: 2000,
      hop_ms: 1000,
      last_chunk_seq: 1,
      inference_ms: 110,
      capture_to_detection_ms: 120,
      rms_dbfs: -22.4,
      dropped_frames_total: 0,
    },
  },
  {
    schema_version: 1,
    event_id: "event-002",
    device_id: "laptop-01",
    stream_id: "stream-01",
    event_seq: 2,

    window_start_at: "2026-09-26T19:34:00.000Z",
    occurred_at: "2026-09-26T19:34:02.000Z",
    detected_at: "2026-09-26T19:34:02.140Z",

    label: "doorbell",
    model_score: 0.91,
    severity: "attention",
    action_id: "check_door",
    source: "fixture",

    processing: {
      model_id: "yamnet/1",
      rule_version: "demo-1",
      sample_rate_hz: 16000,
      window_ms: 2000,
      hop_ms: 1000,
      last_chunk_seq: 3,
      inference_ms: 104,
      capture_to_detection_ms: 140,
      rms_dbfs: -19.1,
      dropped_frames_total: 0,
    },
  },
]
