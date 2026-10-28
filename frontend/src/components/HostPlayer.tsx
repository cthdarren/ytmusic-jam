import { useEffect, useRef, useState } from 'react'
import { next, setPlaying } from '../api'
import {
  ENDED,
  onPlayerEvent,
  PAUSED,
  PLAYING,
  type PlayerEvent,
  REPORT_DELAY_MS,
  shouldReportPause,
  shouldReportPlay,
} from '../hostPlayerLogic'
import type { RoomState } from '../types'

declare global {
  interface Window {
    onYouTubeIframeAPIReady?: () => void
  }
}

let apiPromise: Promise<void> | null = null

function loadYouTubeApi(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve()
  apiPromise ??= new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previous?.()
      resolve()
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.onerror = () => {
      apiPromise = null
      reject(new Error("Couldn't load the YouTube player"))
    }
    document.head.appendChild(script)
  })
  return apiPromise
}

/**
 * The speaker: plays whatever the room says is now playing and reports back when a
 * song ends, fails, or is paused/resumed from the player's own controls.
 */
export function HostPlayer({ state, onError }: { state: RoomState | null; onError: (msg: string) => void }) {
  const [started, setStarted] = useState(false)
  const [ready, setReady] = useState(false)
  const mountRef = useRef<HTMLDivElement>(null)
  const playerRef = useRef<YT.Player | null>(null)
  const loadedItemRef = useRef<string | null>(null)
  // Latest room state for the player's event callbacks, which are bound once.
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const nowPlayingId = state?.now_playing?.id ?? null
  const videoId = state?.now_playing?.track.video_id ?? null
  const isPlaying = state?.is_playing ?? false

  useEffect(() => {
    if (!started || !mountRef.current) return
    let cancelled = false
    let reportTimer: ReturnType<typeof setTimeout> | undefined
    const report = (e: unknown) => onError(e instanceof Error ? e.message : String(e))

    // Play/pause made on the player itself is reported only if it is still true a moment
    // later, so seeks, buffering, end-of-song pauses and our own commands don't echo back.
    const reportLater = (check: (player: YT.Player, roomPlaying: boolean) => boolean, playing: boolean) => {
      clearTimeout(reportTimer)
      reportTimer = setTimeout(() => {
        const player = playerRef.current
        if (player && check(player, stateRef.current?.is_playing ?? false)) setPlaying(playing).catch(report)
      }, REPORT_DELAY_MS)
    }

    const handle = (event: PlayerEvent) => {
      const action = onPlayerEvent(event, stateRef.current?.now_playing?.id ?? null)
      if (action) next(action.expected).catch(report)
    }

    // YT.Player replaces its target with an iframe, so give it a node React doesn't own.
    const container = mountRef.current
    const target = document.createElement('div')
    container.appendChild(target)

    loadYouTubeApi().then(() => {
      if (cancelled) return
      playerRef.current = new YT.Player(target, {
        playerVars: { autoplay: 1, playsinline: 1, rel: 0 },
        events: {
          onReady: () => setReady(true),
          onError: (e) => handle({ kind: 'error', code: Number(e.data) }),
          onStateChange: (e) => {
            if (e.data === ENDED) {
              clearTimeout(reportTimer)
              handle({ kind: 'ended' })
            } else if (e.data === PLAYING) {
              reportLater((player, roomPlaying) => shouldReportPlay({ playerState: player.getPlayerState(), roomPlaying }), true)
            } else if (e.data === PAUSED) {
              reportLater(
                (player, roomPlaying) =>
                  shouldReportPause({
                    playerState: player.getPlayerState(),
                    roomPlaying,
                    currentTime: player.getCurrentTime(),
                    duration: player.getDuration(),
                  }),
                false,
              )
            }
          },
        },
      })
    }, report)

    return () => {
      cancelled = true
      clearTimeout(reportTimer)
      playerRef.current?.destroy()
      playerRef.current = null
      container.replaceChildren()
      loadedItemRef.current = null
      setReady(false)
    }
  }, [started, onError])

  // Load a new song whenever the now-playing item changes (item id, so the same song queued twice replays).
  useEffect(() => {
    const player = playerRef.current
    if (!ready || !player) return
    if (nowPlayingId === null || videoId === null) {
      loadedItemRef.current = null
      player.stopVideo()
      return
    }
    if (loadedItemRef.current === nowPlayingId) return
    loadedItemRef.current = nowPlayingId
    if (stateRef.current?.is_playing) player.loadVideoById(videoId)
    else player.cueVideoById(videoId)
  }, [ready, nowPlayingId, videoId])

  // Follow play/pause from the room (e.g. someone tapped pause on their phone). Always issue the
  // command: the player's own state can lag behind a quick pause→play, and both calls are idempotent.
  useEffect(() => {
    const player = playerRef.current
    if (!ready || !player || nowPlayingId === null) return
    if (isPlaying) player.playVideo()
    else player.pauseVideo()
  }, [ready, isPlaying, nowPlayingId])

  return (
    <section className="host-player">
      <div className="frame">
        {!started ? (
          <div className="host-start">
            <button className="primary" onClick={() => setStarted(true)}>
              Start jam
            </button>
          </div>
        ) : null}
        <div ref={mountRef} />
      </div>
      <p className="muted small">
        This device is the speaker. For no ads, sign into YouTube Premium in this browser (Chrome recommended).
      </p>
    </section>
  )
}
