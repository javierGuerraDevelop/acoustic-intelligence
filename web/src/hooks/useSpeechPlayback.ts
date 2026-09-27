import { useEffect, useRef, useState } from "react"

import {
  requestSpeech,
  updatePlayback,
} from "@/services/api"

const PLAYBACK_RENEW_INTERVAL_MS = 1000

export function useSpeechPlayback() {
  const [isGenerating, setIsGenerating] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const renewTimerRef = useRef<number | null>(null)
  const playbackIdRef = useRef<string | null>(null)

  function stopRenewal() {
    if (renewTimerRef.current !== null) {
      window.clearInterval(renewTimerRef.current)
      renewTimerRef.current = null
    }
  }

  function revokeObjectUrl() {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }

  async function endPlayback() {
    stopRenewal()

    const playbackId = playbackIdRef.current
    playbackIdRef.current = null

    if (playbackId) {
      try {
        await updatePlayback("ended", playbackId)
      } catch {
        // Playback has already ended locally.
        // The UI should not remain stuck because cleanup failed.
      }
    }

    setIsPlaying(false)
    audioRef.current = null
    revokeObjectUrl()
  }

  async function speak(eventId: string) {
    if (isGenerating || isPlaying) {
      return
    }

    setIsGenerating(true)
    setError(null)

    try {
      const audioBlob = await requestSpeech(eventId)
      const objectUrl = URL.createObjectURL(audioBlob)
      const audio = new Audio(objectUrl)
      const playbackId = crypto.randomUUID()

      objectUrlRef.current = objectUrl
      audioRef.current = audio
      playbackIdRef.current = playbackId

      audio.addEventListener(
        "ended",
        () => {
          void endPlayback()
        },
        { once: true }
      )

      audio.addEventListener(
        "error",
        () => {
          setError(new Error("Speech playback failed"))
          void endPlayback()
        },
        { once: true }
      )

      await updatePlayback("started", playbackId)

      await audio.play()

      setIsPlaying(true)

      renewTimerRef.current = window.setInterval(() => {
        void updatePlayback("started", playbackId).catch(
          () => {
            setError(
              new Error(
                "Unable to renew playback state"
              )
            )
          }
        )
      }, PLAYBACK_RENEW_INTERVAL_MS)
    } catch (newError) {
      setError(
        newError instanceof Error
          ? newError
          : new Error("Unable to play speech alert")
      )

      await endPlayback()
    } finally {
      setIsGenerating(false)
    }
  }

  useEffect(() => {
    return () => {
      stopRenewal()

      const audio = audioRef.current

      if (audio) {
        audio.pause()
      }

      const playbackId = playbackIdRef.current

      if (playbackId) {
        void updatePlayback("ended", playbackId)
      }

      revokeObjectUrl()
    }
  }, [])

  return {
    speak,
    isGenerating,
    isPlaying,
    error,
  }
}