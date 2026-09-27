import { useEffect, useState } from "react"

import {
  getSettings,
  updateSettings,
} from "@/services/api"
import type {
  CloudSync,
  Settings,
  UpdateSettingsRequest,
} from "@/types/contracts"

export function useSettings(resetVersion = 0) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [cloudSync, setCloudSync] =
    useState<CloudSync | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isUpdating, setIsUpdating] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadSettings() {
      try {
        const response = await getSettings()

        if (cancelled) {
          return
        }

        setSettings(response)
        setError(null)
      } catch (newError) {
        if (cancelled) {
          return
        }

        setError(
          newError instanceof Error
            ? newError
            : new Error("Failed to load settings")
        )
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadSettings()

    return () => {
      cancelled = true
    }
  }, [resetVersion])

  async function changeSettings(
    changes: UpdateSettingsRequest["changes"]
  ) {
    if (!settings || isUpdating) {
      return
    }

    setIsUpdating(true)
    setError(null)

    try {
      const updatedSettings = await updateSettings({
        schema_version: 1,
        request_id: crypto.randomUUID(),
        expected_revision: settings.revision,
        changes,
      })

      setSettings(updatedSettings)
      setCloudSync(updatedSettings.cloud_sync)
    } catch (newError) {
      setError(
        newError instanceof Error
          ? newError
          : new Error("Failed to update settings")
      )
    } finally {
      setIsUpdating(false)
    }
  }

  return {
    settings,
    cloudSync,
    isLoading,
    isUpdating,
    error,
    changeSettings,
  }
}