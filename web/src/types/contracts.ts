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

export interface SystemState {
  capture: CaptureStatus
  model: ModelStatus
  cloud: CloudStatus
}

export type ChangeType =
  | "event.created"
  | "event.acknowledged"
  | "settings.changed"
  | "job.changed"
  | "history.cleared"

export interface StateChange {
  type: ChangeType
}

export interface StateResponse {
  instance_id: string
  cursor: number
  reset_required: boolean
  state: SystemState
  changes: StateChange[]
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
}

export interface Settings {
  revision: number
  capture_enabled: boolean
  cloud_storage_enabled: boolean
  analytics_enabled: boolean
  speech_enabled: boolean
  retention_days: number
  cooldown_seconds: number
  muted_until: string | null
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

export interface EventHistoryItem {
  event: DetectionEvent
  acknowledged_at: string | null
}

export interface EventHistoryResponse {
  items: EventHistoryItem[]
  next_cursor: string | null
}

export type JobStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"

export interface Job {
  job_id: string
  status: JobStatus
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

export type PlaybackState =
  | "started"
  | "renewed"
  | "ended"

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