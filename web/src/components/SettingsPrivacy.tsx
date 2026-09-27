import { DeleteHistory } from "@/components/DeleteHistory"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import type { Settings } from "@/types/contracts"

interface SettingsPrivacyProps {
  settings: Settings
  isUpdating: boolean
  onChange: (
    changes: Partial<{
      cloud_storage_enabled: boolean
      analytics_enabled: boolean
      speech_enabled: boolean
    }>
  ) => void
  onHistoryDeleted: () => void
}

export function SettingsPrivacy({
  settings,
  isUpdating,
  onChange,
  onHistoryDeleted,
}: SettingsPrivacyProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Settings & Privacy</CardTitle>

        <CardDescription>
          Control optional features that use or share event data.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium">Cloud storage</p>

            <p className="text-sm text-muted-foreground">
              Allow event metadata to be stored in the cloud.
            </p>
          </div>

          <Switch
            checked={settings.cloud_storage_enabled}
            disabled={isUpdating}
            onCheckedChange={(checked) => {
              onChange({
                cloud_storage_enabled: checked,
              })
            }}
            aria-label="Enable cloud storage"
          />
        </div>

        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium">Analytics</p>

            <p className="text-sm text-muted-foreground">
              Allow permitted event metadata to be used for analytics.
            </p>
          </div>

          <Switch
            checked={settings.analytics_enabled}
            disabled={isUpdating}
            onCheckedChange={(checked) => {
              onChange({
                analytics_enabled: checked,
              })
            }}
            aria-label="Enable analytics"
          />
        </div>

        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium">Speech</p>

            <p className="text-sm text-muted-foreground">
              Allow spoken alerts when explicitly requested.
            </p>
          </div>

          <Switch
            checked={settings.speech_enabled}
            disabled={isUpdating}
            onCheckedChange={(checked) => {
              onChange({
                speech_enabled: checked,
              })
            }}
            aria-label="Enable speech"
          />
        </div>

        <div className="border-t pt-6">
          <div className="space-y-3">
            <div>
              <p className="font-medium">
                Detection history
              </p>

              <p className="text-sm text-muted-foreground">
                Permanently delete stored detection history.
              </p>
            </div>

            <DeleteHistory
              onDeleted={onHistoryDeleted}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}