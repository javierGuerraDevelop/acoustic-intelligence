import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { DetectionEvent } from "@/types/contracts"

interface RecentActivityProps {
  events: DetectionEvent[]
}

export function RecentActivity({ events }: RecentActivityProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Activity</CardTitle>
        <CardDescription>
          Recent sound detections from this device.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {events.length > 0 ? (
          events.map((event) => (
            <div
              key={event.event_id}
              className="flex items-center justify-between rounded-lg border p-4"
            >
              <div>
                <p className="font-medium">
                  {event.label === "knock"
                    ? "Possible knocking"
                    : "Possible doorbell"}
                </p>

                <p className="text-sm text-muted-foreground">
                  Model score: {event.model_score.toFixed(2)}
                </p>
              </div>

              <Badge variant="outline">{event.source}</Badge>
            </div>
          ))
        ) : (
          <p className="text-muted-foreground">
            No recent activity.
          </p>
        )}
      </CardContent>
    </Card>
  )
}