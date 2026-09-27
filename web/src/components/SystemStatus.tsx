import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { SystemState } from "@/types/contracts"

interface SystemStatusProps {
  state: SystemState
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
      </CardContent>
    </Card>
  )
}