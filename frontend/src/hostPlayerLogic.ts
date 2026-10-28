export type PlayerEvent = { kind: 'ended' } | { kind: 'error'; code: number }

/**
 * IFrame API errors that mean "this video can't play here": 2 bad id, 5 HTML5 player
 * error, 100 removed/private, 101 and 150 embedding disabled by the owner.
 */
const SKIPPABLE_ERRORS = new Set([2, 5, 100, 101, 150])

/** Decide whether a player event should advance the queue. */
export function onPlayerEvent(event: PlayerEvent, nowPlayingId: string | null): { call: 'next'; expected: string } | null {
  if (nowPlayingId === null) return null
  if (event.kind === 'ended' || SKIPPABLE_ERRORS.has(event.code)) {
    return { call: 'next', expected: nowPlayingId }
  }
  return null
}

// YT.PlayerState values; the YT global only exists once the API script has loaded.
export const ENDED = 0
export const PLAYING = 1
export const PAUSED = 2
export const BUFFERING = 3

/** How long a play/pause on the player must stick before it is reported to the room. */
export const REPORT_DELAY_MS = 400

/**
 * Should a PAUSED event (re-checked after REPORT_DELAY_MS) be reported as the host pausing?
 * Pauses that resolve themselves (seeking, buffering) and the one some players emit just
 * before ENDED must not pause the whole jam.
 */
export function shouldReportPause(p: { playerState: number; roomPlaying: boolean; currentTime: number; duration: number }): boolean {
  if (p.playerState !== PAUSED || !p.roomPlaying) return false
  const nearEnd = p.duration > 0 && p.duration - p.currentTime < 1
  return !nearEnd
}

/** Should a PLAYING event (re-checked after REPORT_DELAY_MS) be reported as the host resuming? */
export function shouldReportPlay(p: { playerState: number; roomPlaying: boolean }): boolean {
  return p.playerState === PLAYING && !p.roomPlaying
}
