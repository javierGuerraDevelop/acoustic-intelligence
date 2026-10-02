import { useState } from "react"

import {
  getJob,
  requestSummary,
} from "@/services/api"
import type { SummaryResult } from "@/types/contracts"

const JOB_POLL_INTERVAL_MS = 1000

function isSummaryResult(
  value: unknown
): value is SummaryResult {
  if (typeof value !== "object" || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>

  return (
    typeof candidate.text === "string" &&
    typeof candidate.event_count === "number" &&
    typeof candidate.counts === "object" &&
    candidate.counts !== null &&
    (typeof candidate.model === "string" ||
      candidate.model === null)
  )
}

export function useActivitySummary() {
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [lastGeneratedAt, setLastGeneratedAt] =
    useState<Date | null>(null)
  const [summary, setSummary] =
    useState<SummaryResult | null>(null)

  async function generateSummary() {
    if (isGenerating) {
      return
    }

    setIsGenerating(true)
    setError(null)

    try {
      let job = await requestSummary()

      while (
        job.state === "pending" ||
        job.state === "running"
      ) {
        await new Promise((resolve) =>
          window.setTimeout(
            resolve,
            JOB_POLL_INTERVAL_MS
          )
        )

        job = await getJob(job.job_id)
      }

      if (job.state !== "complete") {
        throw new Error(
          "Activity summary generation failed"
        )
      }

      if (isSummaryResult(job.result)) {
        setSummary(job.result)
      }

      setLastGeneratedAt(new Date())
    } catch (newError) {
      setError(
        newError instanceof Error
          ? newError
          : new Error(
              "Unable to generate activity summary"
            )
      )
    } finally {
      setIsGenerating(false)
    }
  }

  return {
    generateSummary,
    isGenerating,
    error,
    lastGeneratedAt,
    summary,
  }
}
