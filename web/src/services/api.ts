import { mockEvents } from "@/mocks/events";
import { mockStateResponse } from "@/mocks/stateResponse";
import type {
  AcknowledgeEventRequest,
  AcknowledgeEventResponse,
  DeleteHistoryRequest,
  EventHistoryResponse,
  Job,
  PlaybackRequest,
  PlaybackState,
  Settings,
  SpeechRequest,
  StateResponse,
  SummaryRequest,
  UpdateSettingsRequest,
  UpdateSettingsResponse,
} from "@/types/contracts";

const API_BASE = "/v1";

const USE_MOCK_API =
  import.meta.env.VITE_USE_MOCK_API === "true";

interface GetStateOptions {
  after?: number;
  instanceId?: string;
}

let mockSettings: Settings = {
  schema_version: 1,
  revision: 1,
  capture_enabled: false,
  cloud_storage_enabled: false,
  analytics_enabled: false,
  speech_enabled: false,
  retention_days: 1,
  cooldown_seconds: 10,
  muted_until: null,
};

let mockStateDeliveredInitialChanges = false;

function mockJob(
  kind: Job["kind"],
  state: Job["state"] = "complete",
  result: unknown = null
): Job {
  return {
    schema_version: 1,
    job_id: crypto.randomUUID(),
    kind,
    state,
    updated_at: new Date().toISOString(),
    result,
    error: null,
  };
}

export async function getSystemState({
  after,
  instanceId,
}: GetStateOptions = {}): Promise<StateResponse> {
  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 100)
    );

    const changes = mockStateDeliveredInitialChanges
      ? []
      : mockStateResponse.changes;

    mockStateDeliveredInitialChanges = true;

    return {
      ...mockStateResponse,

      status: {
        ...mockStateResponse.status,
        capture: mockSettings.capture_enabled
          ? "running"
          : "stopped",
      },

      changes,

      cursor:
        after !== undefined
          ? after + 1
          : mockStateResponse.cursor,

      instance_id:
        instanceId ?? mockStateResponse.instance_id,
    };
  }

  const params = new URLSearchParams();

  if (after !== undefined) {
    params.set("after", after.toString());
  }

  if (instanceId) {
    params.set("instance_id", instanceId);
  }

  const query = params.toString();

  const response = await fetch(
    `${API_BASE}/state${query ? `?${query}` : ""}`
  );

  if (!response.ok) {
    throw new Error(
      `Failed to fetch system state: ${response.status}`
    );
  }

  return response.json();
}

export async function getSettings(): Promise<Settings> {
  if (USE_MOCK_API) {
    return { ...mockSettings };
  }

  const response = await fetch(`${API_BASE}/settings`);

  if (!response.ok) {
    throw new Error(
      `Failed to fetch settings: ${response.status}`
    );
  }

  return response.json();
}

export async function updateSettings(
  request: UpdateSettingsRequest
): Promise<UpdateSettingsResponse> {
  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 750)
    );

    if (
      request.expected_revision !==
      mockSettings.revision
    ) {
      throw new Error("Settings revision conflict");
    }

    mockSettings = {
      ...mockSettings,
      ...request.changes,
      revision: mockSettings.revision + 1,
    };

    return { ...mockSettings, cloud_sync: "not_needed" };
  }

  const response = await fetch(`${API_BASE}/settings`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(
      `Failed to update settings: ${response.status}`
    );
  }

  return response.json();
}

export async function acknowledgeEvent(
  eventId: string
): Promise<AcknowledgeEventResponse> {
  const request: AcknowledgeEventRequest = {
    schema_version: 1,
    request_id: crypto.randomUUID(),
  };

  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 300)
    );

    return {
      schema_version: 1,
      event_id: eventId,
      acknowledged_at: new Date().toISOString(),
    };
  }

  const response = await fetch(
    `${API_BASE}/events/${eventId}/ack`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to acknowledge event: ${response.status}`
    );
  }

  return response.json();
}

export async function getEvents(
  limit = 50,
  before?: string
): Promise<EventHistoryResponse> {
  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 150)
    );

    return {
      schema_version: 1,
      items: mockEvents.map((event) => ({
        event,
        acknowledged_at: null,
      })),
      next_cursor: null,
    };
  }

  const params = new URLSearchParams();

  params.set("limit", limit.toString());

  if (before) {
    params.set("before", before);
  }

  const response = await fetch(
    `${API_BASE}/events?${params.toString()}`
  );

  if (!response.ok) {
    throw new Error(
      `Failed to fetch event history: ${response.status}`
    );
  }

  return response.json();
}

export async function deleteHistory(): Promise<Job> {
  const request: DeleteHistoryRequest = {
    schema_version: 1,
    request_id: crypto.randomUUID(),
    scope: "all_history",
  };

  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 500)
    );

    return mockJob("delete", "complete", {
      local: "complete",
      atlas: "complete",
      snowflake: "complete",
    });
  }

  const response = await fetch(
    `${API_BASE}/privacy/delete`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to delete history: ${response.status}`
    );
  }

  return response.json();
}

export async function getJob(
  jobId: string
): Promise<Job> {
  if (USE_MOCK_API) {
    return { ...mockJob("summary"), job_id: jobId };
  }

  const response = await fetch(
    `${API_BASE}/jobs/${jobId}`
  );

  if (!response.ok) {
    throw new Error(
      `Failed to fetch job: ${response.status}`
    );
  }

  return response.json();
}

export async function requestSpeech(
  eventId: string
): Promise<Blob> {
  const request: SpeechRequest = {
    schema_version: 1,
    request_id: crypto.randomUUID(),
    event_id: eventId,
  };

  if (USE_MOCK_API) {
    throw new Error(
      "Speech playback requires the backend integration"
    );
  }

  const response = await fetch(`${API_BASE}/speech`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(
      `Failed to generate speech: ${response.status}`
    );
  }

  return response.blob();
}

export async function updatePlayback(
  state: PlaybackState,
  playbackId: string
): Promise<void> {
  const request: PlaybackRequest = {
    schema_version: 1,
    request_id: crypto.randomUUID(),
    state,
    playback_id: playbackId,
  };

  if (USE_MOCK_API) {
    return;
  }

  const response = await fetch(
    `${API_BASE}/playback`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to update playback state: ${response.status}`
    );
  }
}

export async function requestSummary(): Promise<Job> {
  const request: SummaryRequest = {
    schema_version: 1,
    request_id: crypto.randomUUID(),
    lookback_minutes: 30,
  };

  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 500)
    );

    return mockJob("summary");
  }

  const response = await fetch(
    `${API_BASE}/summary`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to request activity summary: ${response.status}`
    );
  }

  return response.json();
}
