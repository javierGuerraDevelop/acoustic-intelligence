import { useEffect, useState } from "react"

import {
  acknowledgeEvent,
  getEvents,
} from "@/services/api"
import type { EventHistoryItem } from "@/types/contracts"

export function useEventHistory() {
  const [items, setItems] = useState<EventHistoryItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [acknowledgingId, setAcknowledgingId] =
    useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadEvents() {
      try {
        const response = await getEvents()

        if (cancelled) {
          return
        }

        setItems(response.items)
        setError(null)
      } catch (newError) {
        if (cancelled) {
          return
        }

        setError(
          newError instanceof Error
            ? newError
            : new Error("Failed to load event history")
        )
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadEvents()

    return () => {
      cancelled = true
    }
  }, [])

  async function acknowledge(eventId: string) {
    if (acknowledgingId) {
      return
    }

    setAcknowledgingId(eventId)
    setError(null)

    try {
      await acknowledgeEvent(eventId)

      setItems((currentItems) =>
        currentItems.map((item) =>
          item.event.event_id === eventId
            ? {
                ...item,
                acknowledged_at: new Date().toISOString(),
              }
            : item
        )
      )
    } catch (newError) {
      setError(
        newError instanceof Error
          ? newError
          : new Error("Failed to acknowledge event")
      )
    } finally {
      setAcknowledgingId(null)
    }
  }

  function clearHistory() {
    setItems([])
  }

  return {
    items,
    isLoading,
    error,
    acknowledgingId,
    acknowledge,
    clearHistory,
  }
}