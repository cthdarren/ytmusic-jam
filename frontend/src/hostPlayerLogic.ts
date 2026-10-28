export type PlayerEvent = { kind: 'ended' } | { kind: 'error' }

/** Where the host's <audio> element fetches a song; the server downloads it with yt-dlp. */
export function audioUrl(videoId: string): string {
  return `/api/audio/${videoId}`
}

/**
 * Decide whether a player event should advance the queue. Errors skip too: the server has
 * already tried to get the song, so retrying would just stall the jam.
 */
export function onPlayerEvent(_event: PlayerEvent, nowPlayingId: string | null): { call: 'next'; expected: string } | null {
  if (nowPlayingId === null) return null
  return { call: 'next', expected: nowPlayingId }
}

/** How long a play/pause on the host must stick before it is reported to the room. */
export const REPORT_DELAY_MS = 400

/**
 * Should a pause on the host (re-checked after REPORT_DELAY_MS) be reported to the room?
 * Pauses that resolve themselves (seeking) and the one <audio> fires just before `ended`
 * must not pause the whole jam.
 */
export function shouldReportPause(p: { paused: boolean; roomPlaying: boolean; currentTime: number; duration: number }): boolean {
  if (!p.paused || !p.roomPlaying) return false
  const nearEnd = Number.isFinite(p.duration) && p.duration > 0 && p.duration - p.currentTime < 1
  return !nearEnd
}

/** Should playback started on the host (re-checked after REPORT_DELAY_MS) be reported to the room? */
export function shouldReportPlay(p: { paused: boolean; roomPlaying: boolean }): boolean {
  return !p.paused && !p.roomPlaying
}
