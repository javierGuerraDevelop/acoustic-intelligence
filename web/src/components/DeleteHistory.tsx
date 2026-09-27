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

interface DeleteHistoryProps {
  onDeleted: () => void
}

export function DeleteHistory({
  onDeleted,
}: DeleteHistoryProps) {
  const [isDeleting, setIsDeleting] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function handleDelete() {
    if (isDeleting) {
      return
    }

    setIsDeleting(true)
    setError(null)

    try {
      let job = await deleteHistory()

      while (
        job.status === "pending" ||
        job.status === "running"
      ) {
        await new Promise((resolve) =>
          window.setTimeout(resolve, 1000)
        )

        job = await getJob(job.job_id)
      }

      if (job.status === "failed") {
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
    }
  }

  return (
    <div className="space-y-2">
      <AlertDialog>
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

      {error && (
        <p className="text-sm text-destructive">
          Unable to delete detection history.
        </p>
      )}
    </div>
  )
}