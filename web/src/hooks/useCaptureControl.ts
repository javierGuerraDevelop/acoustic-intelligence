import { useState } from "react"

import { getSettings, updateSettings } from "@/services/api"
import type { CaptureStatus } from "@/types/contracts"

export function useCaptureControl(status: CaptureStatus) {
  const [isUpdating, setIsUpdating] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function toggleCapture() {
    if (isUpdating) {
      return
    }

    setIsUpdating(true)
    setError(null)

    try {
      const settings = await getSettings()

      await updateSettings({
        schema_version: 1,
        request_id: crypto.randomUUID(),
        expected_revision: settings.revision,
        changes: {
          capture_enabled: status !== "running",
        },
      })
    } catch (newError) {
      setError(
        newError instanceof Error
          ? newError
          : new Error("Failed to update capture")
      )
    } finally {
      setIsUpdating(false)
    }
  }

  return {
    toggleCapture,
    isUpdating,
    error,
  }
}