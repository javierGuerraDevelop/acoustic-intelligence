import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { EventHistoryItem } from "@/types/contracts"

interface LatestDetectionProps {
  item?: EventHistoryItem
  isAcknowledging: boolean
  onAcknowledge: (eventId: string) => void
}

export function LatestDetection({
  item,
  isAcknowledging,
  onAcknowledge,
}: LatestDetectionProps) {
  const event = item?.event
  const acknowledged = item?.acknowledged_at !== null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Latest Detection</CardTitle>
      </CardHeader>

      <CardContent>
        {event ? (
          <div className="space-y-3">
            <div>
              <p className="text-2xl font-semibold">
                {event.label === "knock"
                  ? "Possible knocking"
                  : "Possible doorbell"}
              </p>

              <p className="text-muted-foreground">
                Check the door
              </p>
            </div>

            <div className="flex gap-2">
              <Badge>{event.severity}</Badge>

              <Badge variant="outline">
                Model score: {event.model_score.toFixed(2)}
              </Badge>

              {acknowledged && (
                <Badge variant="secondary">
                  Acknowledged
                </Badge>
              )}
            </div>

            <Button
              variant="outline"
              disabled={isAcknowledging || acknowledged}
              onClick={() => {
                onAcknowledge(event.event_id)
              }}
            >
              {isAcknowledging
                ? "Acknowledging..."
                : acknowledged
                  ? "Acknowledged"
                  : "Acknowledge"}
            </Button>
          </div>
        ) : (
          <p className="text-muted-foreground">
            No detections yet.
          </p>
        )}
      </CardContent>
    </Card>
  )
}