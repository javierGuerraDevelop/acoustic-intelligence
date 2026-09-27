import { LatestDetection } from "@/components/LatestDetection"
import { ListeningStatus } from "@/components/ListeningStatus"
import { RecentActivity } from "@/components/RecentActivity"
import { SettingsPrivacy } from "@/components/SettingsPrivacy"
import { SystemStatus } from "@/components/SystemStatus"
import { Badge } from "@/components/ui/badge"
import { useCaptureControl } from "@/hooks/useCaptureControl"
import { useEventHistory } from "@/hooks/useEventHistory"
import { useSettings } from "@/hooks/useSettings"
import { useSystemState } from "@/hooks/useSystemState"

function App() {
  const { response, error: pollingError } = useSystemState()

  const {
    items: historyItems,
    isLoading: historyLoading,
    error: historyError,
    acknowledgingId,
    acknowledge,
    clearHistory,
  } = useEventHistory()

  const {
    settings,
    isLoading: settingsLoading,
    isUpdating: settingsUpdating,
    error: settingsError,
    changeSettings,
  } = useSettings()

  const events = historyItems.map((item) => item.event)
  const latestItem = historyItems[0]

  const systemState = response?.state ?? {
    capture: "stopped" as const,
    model: "loading" as const,
    cloud: "disabled" as const,
  }

  const {
    toggleCapture,
    isUpdating: captureUpdating,
    error: captureError,
  } = useCaptureControl(systemState.capture)

  return (
    <main className="min-h-screen bg-background p-6">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Live Sound Radar
            </h1>

            <p className="text-muted-foreground">
              Local sound awareness dashboard
            </p>
          </div>

          <Badge variant="secondary">
            {pollingError ? "Disconnected" : "Local"}
          </Badge>
        </header>

        <SystemStatus state={systemState} />

        <ListeningStatus
          status={
            captureUpdating
              ? systemState.capture === "running"
                ? "stopping"
                : "starting"
              : systemState.capture
          }
          onToggle={() => {
            void toggleCapture()
          }}
        />

        {captureError && (
          <p className="text-sm text-destructive">
            Unable to change listening state.
          </p>
        )}

        {historyLoading ? (
          <p className="text-muted-foreground">
            Loading detections...
          </p>
        ) : historyError ? (
          <p className="text-sm text-destructive">
            Unable to load detection history.
          </p>
        ) : (
          <>
            <LatestDetection
              item={latestItem}
              isAcknowledging={
                acknowledgingId === latestItem?.event.event_id
              }
              onAcknowledge={(eventId) => {
                void acknowledge(eventId)
              }}
            />

            <RecentActivity events={events} />
          </>
        )}

        {settingsLoading ? (
          <p className="text-muted-foreground">
            Loading settings...
          </p>
        ) : settingsError ? (
          <p className="text-sm text-destructive">
            Unable to load settings.
          </p>
        ) : settings ? (
          <SettingsPrivacy
            settings={settings}
            isUpdating={settingsUpdating}
            onChange={(changes) => {
              void changeSettings(changes)
            }}
            onHistoryDeleted={clearHistory}
          />
        ) : null}
      </div>
    </main>
  )
}

export default App