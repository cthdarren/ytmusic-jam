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
