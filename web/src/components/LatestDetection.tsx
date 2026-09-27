import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { EventHistoryItem } from "@/types/contracts";

interface LatestDetectionProps {
  item?: EventHistoryItem;
  isAcknowledging: boolean;
  speechEnabled: boolean;
  isGeneratingSpeech: boolean;
  isPlayingSpeech: boolean;
  onAcknowledge: (eventId: string) => void;
  onSpeak: (eventId: string) => void;
}

export function LatestDetection({
  item,
  isAcknowledging,
  speechEnabled,
  isGeneratingSpeech,
  isPlayingSpeech,
  onAcknowledge,
  onSpeak,
}: LatestDetectionProps) {
  const event = item?.event;
  const acknowledged = item?.acknowledged_at != null;

  if (!event) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Latest Detection</CardTitle>
        </CardHeader>

        <CardContent>
          <p className="text-muted-foreground">
            No detections yet.
          </p>
        </CardContent>
      </Card>
    );
  }

  const detectionLabel =
    event.label === "knock"
      ? "Possible knocking"
      : "Possible doorbell";

  return (
    <Card
      className={
        acknowledged
          ? ""
          : "border-2 border-foreground"
      }
    >
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Latest Detection</CardTitle>

          {!acknowledged && (
            <Badge>Needs attention</Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <p className="text-3xl font-bold">
            {detectionLabel}
          </p>

          <p className="mt-1 text-lg font-medium">
            Check the door
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">
            {event.severity}
          </Badge>

          <Badge variant="outline">
            Model score: {event.model_score.toFixed(2)}
          </Badge>

          {acknowledged && (
            <Badge variant="secondary">
              Acknowledged
            </Badge>
          )}
        </div>

        {isPlayingSpeech && (
          <p
            className="text-sm font-medium"
            role="status"
            aria-live="polite"
          >
            Speech playing; detection temporarily paused.
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={
              isAcknowledging || acknowledged
            }
            onClick={() => {
              onAcknowledge(event.event_id);
            }}
          >
            {isAcknowledging
              ? "Acknowledging..."
              : acknowledged
                ? "Acknowledged"
                : "Acknowledge"}
          </Button>

          <Button
            disabled={
              !speechEnabled ||
              isGeneratingSpeech ||
              isPlayingSpeech
            }
            onClick={() => {
              onSpeak(event.event_id);
            }}
          >
            {isGeneratingSpeech
              ? "Generating Speech..."
              : isPlayingSpeech
                ? "Playing..."
                : "Speak Alert"}
          </Button>
        </div>

        {!speechEnabled && (
          <p className="text-sm text-muted-foreground">
            Enable Speech in Settings & Privacy to use
            spoken alerts.
          </p>
        )}
      </CardContent>
    </Card>
  );
}