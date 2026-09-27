import type { StateResponse } from "@/types/contracts"

export const mockStateResponse: StateResponse = {
  instance_id: "local-instance-001",
  cursor: 2,
  reset_required: false,

  state: {
    capture: "stopped",
    model: "ready",
    cloud: "disabled",
  },

  changes: [
    {
      type: "event.created",
    },
    {
      type: "event.created",
    },
  ],
}