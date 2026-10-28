import { useEffect, useRef, useState } from 'react'
import { next, setPlaying } from '../api'
import {
  audioUrl,
  onPlayerEvent,
  type PlayerEvent,
  REPORT_DELAY_MS,
  shouldReportPause,
  shouldReportPlay,
} from '../hostPlayerLogic'
import type { RoomState } from '../types'

/**
 * The speaker: plays the room's current song from the server (which fetches it with yt-dlp)
 * and reports back when a song ends, fails, or is paused/resumed on this device.
 */
export function HostPlayer({ state, onError }: { state: RoomState | null; onError: (msg: string) => void }) {
  const [started, setStarted] = useState(false)
  const [loading, setLoading] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  // The queue item whose audio is loaded; events are reported against it, not whatever is current now.
  const loadedItemRef = useRef<string | null>(null)
  const reportTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // Latest room state for the audio event handlers.
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const nowPlaying = state?.now_playing ?? null
  const nowPlayingId = nowPlaying?.id ?? null
  const videoId = nowPlaying?.track.video_id ?? null
  const isPlaying = state?.is_playing ?? false

  const report = (e: unknown) => onError(e instanceof Error ? e.message : String(e))

  const load = (audio: HTMLAudioElement, itemId: string, id: string) => {
    loadedItemRef.current = itemId
    audio.src = audioUrl(id)
    if (stateRef.current?.is_playing) audio.play().catch(() => {}) // superseded loads reject; errors arrive via onError
  }

  // "Start jam" must call play() inside the click, or browsers block audio with sound.
  const start = () => {
    setStarted(true)
    const audio = audioRef.current
    if (audio && nowPlayingId && videoId) load(audio, nowPlayingId, videoId)
  }

  // Load a new song whenever the now-playing item changes (item id, so the same song queued twice replays).
  useEffect(() => {
    const audio = audioRef.current
    if (!started || !audio) return
    if (nowPlayingId === null || videoId === null) {
      loadedItemRef.current = null
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
      return
    }
    if (loadedItemRef.current !== nowPlayingId) load(audio, nowPlayingId, videoId)
  }, [started, nowPlayingId, videoId])

  // Follow play/pause from the room (e.g. someone tapped pause on their phone).
  useEffect(() => {
    const audio = audioRef.current
    if (!started || !audio || nowPlayingId === null) return
    if (isPlaying) audio.play().catch(() => {})
    else audio.pause()
  }, [started, isPlaying, nowPlayingId])

  useEffect(() => () => clearTimeout(reportTimer.current), [])

  const handle = (event: PlayerEvent) => {
    clearTimeout(reportTimer.current)
    const action = onPlayerEvent(event, loadedItemRef.current)
    if (action) next(action.expected).catch(report)
  }

  // Play/pause made on this device is reported only if it is still true a moment later,
  // so seeks, the pause <audio> fires before `ended`, and our own commands don't echo back.
  const reportLater = (check: (audio: HTMLAudioElement, roomPlaying: boolean) => boolean, playing: boolean) => {
    clearTimeout(reportTimer.current)
    reportTimer.current = setTimeout(() => {
      const audio = audioRef.current
      if (audio && loadedItemRef.current && check(audio, stateRef.current?.is_playing ?? false)) {
        setPlaying(playing).catch(report)
      }
    }, REPORT_DELAY_MS)
  }

  const art = nowPlaying?.track.thumbnail_url

  return (
    <section className="host-player">
      <div className="now-card">
        {art ? <img className="art" src={art} alt="" referrerPolicy="no-referrer" /> : <div className="art art-empty" aria-hidden>♪</div>}
        <div className="now-card-text">
          <span className="track-title">{nowPlaying?.track.title ?? 'Nothing playing'}</span>
          <span className="track-meta">{nowPlaying?.track.artist}</span>
          {loading && nowPlaying ? <span className="muted small">Loading…</span> : null}
        </div>
        {!started ? (
          <button className="primary" onClick={start}>
            Start jam
          </button>
        ) : null}
      </div>
      <audio
        ref={audioRef}
        className="host-audio"
        controls
        preload="auto"
        onLoadStart={() => setLoading(true)}
        onWaiting={() => setLoading(true)}
        onCanPlay={() => setLoading(false)}
        onPlaying={() => {
          setLoading(false)
          reportLater((audio, roomPlaying) => shouldReportPlay({ paused: audio.paused, roomPlaying }), true)
        }}
        onPause={() =>
          reportLater(
            (audio, roomPlaying) =>
              shouldReportPause({ paused: audio.paused, roomPlaying, currentTime: audio.currentTime, duration: audio.duration }),
            false,
          )
        }
        onEnded={() => handle({ kind: 'ended' })}
        onError={() => {
          if (!loadedItemRef.current) return // src was cleared on purpose
          setLoading(false)
          onError(`Couldn't play ${stateRef.current?.now_playing?.track.title ?? 'that song'} — skipping`)
          handle({ kind: 'error' })
        }}
      />
      <p className="muted small">This device is the speaker — keep this tab open.</p>
    </section>
  )
}
