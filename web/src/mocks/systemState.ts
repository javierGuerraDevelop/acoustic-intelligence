import type { RuntimeStatus } from "@/types/contracts"

export const mockSystemState: RuntimeStatus = {
  capture: "stopped",
  model: "ready",
  cloud: "disabled",
  export_pending: 0,
  export_dropped: 0,
  audio_gaps: 0,
}
