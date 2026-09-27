import { useEffect, useRef, useState } from "react"

import { startStatePolling } from "@/services/pollState"
import type { StateResponse } from "@/types/contracts"

const DISCONNECTED_AFTER_MS = 2000
const CONNECTION_CHECK_INTERVAL_MS = 250

export function useSystemState() {
  const [response, setResponse] =
    useState<StateResponse | null>(null)

  const [isDisconnected, setIsDisconnected] =
    useState(false)

  const [resetVersion, setResetVersion] =
    useState(0)

  const [eventVersion, setEventVersion] =
    useState(0)

  const lastSuccessRef = useRef<number | null>(null)
  const resetActiveRef = useRef(false)

  useEffect(() => {
    let stopPolling: (() => void) | null = null

    function startPolling() {
      if (stopPolling) {
        return
      }

      stopPolling = startStatePolling({
        onState: (newResponse) => {
          lastSuccessRef.current = Date.now()

          setResponse(newResponse)
          setIsDisconnected(false)

          if (
            newResponse.reset_required &&
            !resetActiveRef.current
          ) {
            resetActiveRef.current = true
            setResetVersion((current) => current + 1)
          }

          if (!newResponse.reset_required) {
            resetActiveRef.current = false
          }

          const hasEventChange =
            newResponse.changes.some(
              (change) =>
                change.type === "event.created" ||
                change.type === "event.acknowledged" ||
                change.type === "history.cleared"
            )

          if (hasEventChange) {
            setEventVersion((current) => current + 1)
          }
        },

        onError: () => {
          // A single failed request does not immediately mean
          // the local service is disconnected.
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
        return
      }

      lastSuccessRef.current = null
      setIsDisconnected(false)

      startPolling()
    }

    if (!document.hidden) {
      startPolling()
    }

    const connectionTimer = window.setInterval(() => {
      if (document.hidden) {
        return
      }

      const lastSuccess = lastSuccessRef.current

      if (lastSuccess === null) {
        return
      }

      setIsDisconnected(
        Date.now() - lastSuccess >
          DISCONNECTED_AFTER_MS
      )
    }, CONNECTION_CHECK_INTERVAL_MS)

    document.addEventListener(
      "visibilitychange",
      handleVisibilityChange
    )

    return () => {
      stopCurrentPolling()

      window.clearInterval(connectionTimer)

      document.removeEventListener(
        "visibilitychange",
        handleVisibilityChange
      )
    }
  }, [])

  return {
    response,
    isDisconnected,
    resetVersion,
    eventVersion,
  }
}