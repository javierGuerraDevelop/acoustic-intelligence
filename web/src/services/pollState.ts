import { getSystemState } from "@/services/api"
import type { StateResponse } from "@/types/contracts"

const POLL_INTERVAL_MS = 250

interface PollStateOptions {
  onState: (response: StateResponse) => void
  onError: (error: Error) => void
}

export function startStatePolling({
  onState,
  onError,
}: PollStateOptions) {
  let stopped = false
  let cursor: number | undefined
  let instanceId: string | undefined

  async function poll() {
    if (stopped) {
      return
    }

    try {
      const response = await getSystemState({
        after: cursor,
        instanceId,
      })

      if (stopped) {
        return
      }

      cursor = response.cursor
      instanceId = response.instance_id

      onState(response)
    } catch (error) {
      if (!stopped) {
        onError(
          error instanceof Error
            ? error
            : new Error("Unknown polling error")
        )
      }
    }

    if (!stopped) {
      window.setTimeout(poll, POLL_INTERVAL_MS)
    }
  }

  void poll()

  return function stopPolling() {
    stopped = true
  }
}