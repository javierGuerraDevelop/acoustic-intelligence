import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { CaptureStatus } from "@/types/contracts"

interface ListeningStatusProps {
  status: CaptureStatus
  onToggle: () => void
}

export function ListeningStatus({
  status,
  onToggle,
}: ListeningStatusProps) {
  const isRunning = status === "running"
  const isTransitioning =
    status === "starting" || status === "stopping"

  const statusMessage = {
    stopped: "Sound detection is currently stopped.",
    starting: "Sound detection is starting...",
    running: "Sound detection is currently running.",
    stopping: "Sound detection is stopping...",
    error: "Sound detection encountered an error.",
  }[status]

  return (
    <Card>
      <CardHeader>
        <CardTitle>Listening Status</CardTitle>
        <CardDescription>{statusMessage}</CardDescription>
      </CardHeader>

      <CardContent>
        <Button
          onClick={onToggle}
          disabled={isTransitioning}
        >
          {status === "starting"
            ? "Starting..."
            : status === "stopping"
              ? "Stopping..."
              : isRunning
                ? "Stop Listening"
                : "Start Listening"}
        </Button>
      </CardContent>
    </Card>
  )
}