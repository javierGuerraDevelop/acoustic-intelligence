import { mockEvents } from "@/mocks/events"
import type { StateResponse } from "@/types/contracts"

export const mockStateResponse: StateResponse = {
  schema_version: 1,
  instance_id: "local-instance-001",
  cursor: 1,
  reset_required: false,

  status: {
    capture: "stopped",
    model: "ready",
    cloud: "disabled",
    export_pending: 0,
    export_dropped: 0,
    audio_gaps: 0,
  },

  changes: [
    {
      cursor: 1,
      type: "event.created",
      event_id: mockEvents[0].event_id,
      data: { event: mockEvents[0] },
    },
  ],
}
