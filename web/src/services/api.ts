import { mockStateResponse } from "@/mocks/stateResponse";
import type {
  AcknowledgeEventRequest,
  DeleteHistoryRequest,
  EventHistoryResponse,
  Job,
  PlaybackRequest,
  Settings,
  SpeechRequest,
  StateResponse,
  SummaryRequest,
  UpdateSettingsRequest,
} from "@/types/contracts";

const API_BASE = "/v1";

const USE_MOCK_API =
  import.meta.env.VITE_USE_MOCK_API === "true";

interface GetStateOptions {
  after?: number;
  instanceId?: string;
}

let mockSettings: Settings = {
  revision: 1,
  capture_enabled: false,
  cloud_storage_enabled: false,
  analytics_enabled: false,
  speech_enabled: false,
  retention_days: 7,
  cooldown_seconds: 5,
  muted_until: null,
};

let mockStateDeliveredInitialChanges = false;

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

      state: {
        ...mockStateResponse.state,
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
): Promise<Settings> {
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

    return { ...mockSettings };
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
): Promise<void> {
  const request: AcknowledgeEventRequest = {
    schema_version: 1,
    request_id: crypto.randomUUID(),
  };

  if (USE_MOCK_API) {
    await new Promise((resolve) =>
      window.setTimeout(resolve, 300)
    );

    return;
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
}

export async function getEvents(
  limit = 50,
  before?: string
): Promise<EventHistoryResponse> {
  if (USE_MOCK_API) {
    const { mockEvents } = await import(
      "@/mocks/events"
    );

    await new Promise((resolve) =>
      window.setTimeout(resolve, 150)
    );

    return {
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

    return {
      job_id: crypto.randomUUID(),
      status: "completed",
    };
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
    return {
      job_id: jobId,
      status: "completed",
    };
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
  state: PlaybackRequest["state"],
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

    return {
      job_id: crypto.randomUUID(),
      status: "completed",
    };
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