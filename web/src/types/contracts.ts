export type EventLabel = "knock" | "doorbell"

export type EventSeverity = "info" | "attention"

export type EventAction = "check_door"

export type EventSource = "microphone" | "fixture"

export type CaptureStatus =
  | "stopped"
  | "starting"
  | "running"
  | "stopping"
  | "error"

export type ModelStatus =
  | "loading"
  | "ready"
  | "error"

export type CloudStatus =
  | "disabled"
  | "online"
  | "degraded"
  | "offline"

export interface RuntimeStatus {
  capture: CaptureStatus
  model: ModelStatus
  cloud: CloudStatus
  export_pending: number
  export_dropped: number
  audio_gaps: number
}

export interface EventProcessing {
  model_id: string
  rule_version: string
  sample_rate_hz: number
  window_ms: number
  hop_ms: number
  last_chunk_seq: number
  inference_ms: number
  capture_to_detection_ms: number
  rms_dbfs: number
  dropped_frames_total: number
}

export interface DetectionEvent {
  schema_version: number
  event_id: string
  device_id: string
  stream_id: string
  event_seq: number

  window_start_at: string
  occurred_at: string
  detected_at: string

  label: EventLabel
  model_score: number
  severity: EventSeverity
  action_id: EventAction
  source: EventSource

  processing: EventProcessing
}

export type ChangeType =
  | "event.created"
  | "event.acknowledged"
  | "settings.changed"
  | "job.changed"
  | "history.cleared"

export type StateChange =
  | {
      cursor: number
      type: "event.created"
      event_id: string
      data: { event: DetectionEvent }
    }
  | {
      cursor: number
      type: "event.acknowledged"
      event_id: string
      data: { event_id: string; acknowledged_at: string }
    }
  | {
      cursor: number
      type: "settings.changed"
      data: { settings: Settings }
    }
  | {
      cursor: number
      type: "job.changed"
      data: { job: Job }
    }
  | {
      cursor: number
      type: "history.cleared"
      data: { deletion_id: string }
    }

export interface StateResponse {
  schema_version: number
  instance_id: string
  cursor: number
  reset_required: boolean
  status: RuntimeStatus
  changes: StateChange[]
}

export interface Settings {
  schema_version: number
  revision: number
  capture_enabled: boolean
  cloud_storage_enabled: boolean
  analytics_enabled: boolean
  speech_enabled: boolean
  retention_days: number
  cooldown_seconds: number
  muted_until: string | null
}

export type CloudSync = "not_needed" | "pending" | "complete"

export interface UpdateSettingsResponse extends Settings {
  cloud_sync: CloudSync
}

export interface UpdateSettingsRequest {
  schema_version: 1
  request_id: string
  expected_revision: number
  changes: Partial<{
    capture_enabled: boolean
    cloud_storage_enabled: boolean
    analytics_enabled: boolean
    speech_enabled: boolean
    retention_days: number
    cooldown_seconds: number
    muted_until: string | null
  }>
}

export interface AcknowledgeEventRequest {
  schema_version: 1
  request_id: string
}

export interface AcknowledgeEventResponse {
  schema_version: number
  event_id: string
  acknowledged_at: string
}

export interface EventHistoryItem {
  event: DetectionEvent
  acknowledged_at: string | null
}

export interface EventHistoryResponse {
  schema_version: number
  items: EventHistoryItem[]
  next_cursor: string | null
}

export type JobKind = "delete" | "summary"

export type JobState = "pending" | "running" | "complete" | "failed"

export interface Job {
  schema_version: number
  job_id: string
  kind: JobKind
  state: JobState
  updated_at: string
  result: unknown
  error: unknown
}

export interface DeleteHistoryRequest {
  schema_version: 1
  request_id: string
  scope: "all_history"
}

export interface SpeechRequest {
  schema_version: 1
  request_id: string
  event_id: string
}

export type PlaybackState = "started" | "ended"

export interface PlaybackRequest {
  schema_version: 1
  request_id: string
  state: PlaybackState
  playback_id: string
}

export interface SummaryRequest {
  schema_version: 1
  request_id: string
  lookback_minutes: number
}
