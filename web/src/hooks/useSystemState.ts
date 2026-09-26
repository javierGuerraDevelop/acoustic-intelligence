import { useEffect, useState } from "react"

import { startStatePolling } from "@/services/pollState"
import type { StateResponse } from "@/types/contracts"

export function useSystemState() {
  const [response, setResponse] = useState<StateResponse | null>(null)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    let stopPolling: (() => void) | null = null

    function startPolling() {
      if (stopPolling) {
        return
      }

      stopPolling = startStatePolling({
        onState: (newResponse) => {
          setResponse(newResponse)
          setError(null)
        },

        onError: (newError) => {
          setError(newError)
        },
      })
    }

    function stopCurrentPolling() {
      if (stopPolling) {
        stopPolling()
        stopPolling = null
      }
    }

    function handleVisibilityChange() {
      if (document.hidden) {
        stopCurrentPolling()
      } else {
        startPolling()
      }
    }

    if (!document.hidden) {
      startPolling()
    }

    document.addEventListener(
      "visibilitychange",
      handleVisibilityChange
    )

    return () => {
      stopCurrentPolling()

      document.removeEventListener(
        "visibilitychange",
        handleVisibilityChange
      )
    }
  }, [])

  return {
    response,
    error,
  }
}