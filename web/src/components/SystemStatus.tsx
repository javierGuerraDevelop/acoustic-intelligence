import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { RuntimeStatus } from "@/types/contracts"

interface SystemStatusProps {
  state: RuntimeStatus
}

export function SystemStatus({ state }: SystemStatusProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>System Status</CardTitle>
      </CardHeader>

      <CardContent className="flex flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Capture</span>
          <Badge variant="outline">{state.capture}</Badge>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Model</span>
          <Badge variant="outline">{state.model}</Badge>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">Cloud</span>
          <Badge variant="outline">{state.cloud}</Badge>
        </div>

        {state.export_pending > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              Export pending
            </span>
            <Badge variant="outline">
              {state.export_pending}
            </Badge>
          </div>
        )}

        {state.export_dropped > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              Export dropped
            </span>
            <Badge variant="outline">
              {state.export_dropped}
            </Badge>
          </div>
        )}

        {state.audio_gaps > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              Audio gaps
            </span>
            <Badge variant="outline">
              {state.audio_gaps}
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  )
}