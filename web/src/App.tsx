import { ActivitySummary } from "@/components/ActivitySummary";
import { LatestDetection } from "@/components/LatestDetection";
import { ListeningStatus } from "@/components/ListeningStatus";
import { RecentActivity } from "@/components/RecentActivity";
import { SettingsPrivacy } from "@/components/SettingsPrivacy";
import { SystemStatus } from "@/components/SystemStatus";
import { Badge } from "@/components/ui/badge";
import { useActivitySummary } from "@/hooks/useActivitySummary";
import { useCaptureControl } from "@/hooks/useCaptureControl";
import { useEventHistory } from "@/hooks/useEventHistory";
import { useSettings } from "@/hooks/useSettings";
import { useSpeechPlayback } from "@/hooks/useSpeechPlayback";
import { useSystemState } from "@/hooks/useSystemState";

function App() {
  const {
    response,
    isDisconnected,
    resetVersion,
    eventVersion,
  } = useSystemState();

  const {
    items: historyItems,
    isLoading: historyLoading,
    error: historyError,
    acknowledgingId,
    acknowledge,
    clearHistory,
  } = useEventHistory(resetVersion, eventVersion);

  const {
    settings,
    cloudSync,
    isLoading: settingsLoading,
    isUpdating: settingsUpdating,
    error: settingsError,
    changeSettings,
  } = useSettings(resetVersion);

  const {
    speak,
    isGenerating: isGeneratingSpeech,
    isPlaying: isPlayingSpeech,
    error: speechError,
  } = useSpeechPlayback();

  const {
    generateSummary,
    isGenerating: isGeneratingSummary,
    error: summaryError,
    lastGeneratedAt,
    summary,
  } = useActivitySummary();

  const events = historyItems.map((item) => item.event);
  const latestItem = historyItems[0];

  const systemState = response?.status ?? {
    capture: "stopped" as const,
    model: "loading" as const,
    cloud: "disabled" as const,
    export_pending: 0,
    export_dropped: 0,
    audio_gaps: 0,
  };

  const {
    toggleCapture,
    isUpdating: captureUpdating,
    error: captureError,
  } = useCaptureControl(systemState.capture);

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
            {isDisconnected ? "Disconnected" : "Local"}
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
            void toggleCapture();
          }}
        />

        {captureError && (
          <p
            className="text-sm text-destructive"
            role="alert"
          >
            Unable to change listening state.
          </p>
        )}

        {historyLoading ? (
          <p className="text-muted-foreground">
            Loading detections...
          </p>
        ) : historyError ? (
          <p
            className="text-sm text-destructive"
            role="alert"
          >
            Unable to load detection history.
          </p>
        ) : (
          <>
            <LatestDetection
              item={latestItem}
              isAcknowledging={
                acknowledgingId ===
                latestItem?.event.event_id
              }
              speechEnabled={
                settings?.speech_enabled ?? false
              }
              isGeneratingSpeech={isGeneratingSpeech}
              isPlayingSpeech={isPlayingSpeech}
              onAcknowledge={(eventId) => {
                void acknowledge(eventId);
              }}
              onSpeak={(eventId) => {
                void speak(eventId);
              }}
            />

            {speechError && (
              <p
                className="text-sm text-destructive"
                role="alert"
              >
                Unable to play spoken alert.
              </p>
            )}

            <RecentActivity events={events} />
          </>
        )}

        <ActivitySummary
          analyticsEnabled={
            settings?.analytics_enabled ?? false
          }
          isGenerating={isGeneratingSummary}
          lastGeneratedAt={lastGeneratedAt}
          summary={summary}
          error={summaryError}
          onGenerate={() => {
            void generateSummary();
          }}
        />

        {settingsLoading ? (
          <p className="text-muted-foreground">
            Loading settings...
          </p>
        ) : settingsError ? (
          <p
            className="text-sm text-destructive"
            role="alert"
          >
            Unable to load settings.
          </p>
        ) : settings ? (
          <SettingsPrivacy
            settings={settings}
            cloudSync={cloudSync}
            isUpdating={settingsUpdating}
            onChange={(changes) => {
              void changeSettings(changes);
            }}
            onHistoryDeleted={clearHistory}
          />
        ) : null}
      </div>
    </main>
  );
}

export default App;