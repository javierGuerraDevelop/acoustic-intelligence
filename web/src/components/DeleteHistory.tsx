import { useState } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  deleteHistory,
  getJob,
} from "@/services/api"
import type { DeleteHistoryResult } from "@/types/contracts"

interface DeleteHistoryProps {
  onDeleted: () => void
}

function isDeleteHistoryResult(
  value: unknown
): value is DeleteHistoryResult {
  if (typeof value !== "object" || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>

  return (
    candidate.local === "complete" &&
    typeof candidate.atlas === "string" &&
    typeof candidate.snowflake === "string"
  )
}

export function DeleteHistory({
  onDeleted,
}: DeleteHistoryProps) {
  const [isDeleting, setIsDeleting] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  async function handleDelete() {
    if (isDeleting) {
      return
    }

    setIsDeleting(true)
    setError(null)
    setNotice(null)

    try {
      let job = await deleteHistory()

      while (
        job.state === "pending" ||
        job.state === "running"
      ) {
        await new Promise((resolve) =>
          window.setTimeout(resolve, 1000)
        )

        job = await getJob(job.job_id)
      }

      const result = isDeleteHistoryResult(job.result)
        ? job.result
        : null

      if (
        job.state === "failed" &&
        result?.local === "complete"
      ) {
        // Local history is gone; only the cloud copy is
        // unconfirmed, so this is a pending state rather
        // than a deletion failure.
        setNotice(
          "Local history was deleted. Cloud deletion could not be confirmed and remains pending; run Delete History again to retry."
        )
        onDeleted()
        return
      }

      if (job.state !== "complete") {
        throw new Error("History deletion failed")
      }

      onDeleted()
    } catch (newError) {
      setError(
        newError instanceof Error
          ? newError
          : new Error("Failed to delete history")
      )
    } finally {
      setIsDeleting(false)
      setDialogOpen(false)
    }
  }

  return (
    <div className="space-y-2">
      <AlertDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      >
        <AlertDialogTrigger asChild>
          <Button variant="destructive">
            Delete History
          </Button>
        </AlertDialogTrigger>

        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete all detection history?
            </AlertDialogTitle>

            <AlertDialogDescription>
              This permanently deletes your stored detection
              history. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>
              Cancel
            </AlertDialogCancel>

            <AlertDialogAction
              disabled={isDeleting}
              onClick={(event) => {
                event.preventDefault()
                void handleDelete()
              }}
            >
              {isDeleting
                ? "Deleting..."
                : "Delete History"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {notice && (
        <p
          className="text-sm text-muted-foreground"
          role="status"
        >
          {notice}
        </p>
      )}

      {error && (
        <p className="text-sm text-destructive">
          Unable to delete detection history.
        </p>
      )}
    </div>
  )
}