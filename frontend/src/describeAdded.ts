import type { RoomState } from './types'

/**
 * Toast text after adding a link, naming the song that was queued so a wrong Spotify match is
 * easy to spot. A new song goes to the end of the queue, or starts playing if nothing was.
 */
export function describeAdded(state: RoomState): string {
  const added = state.queue.length > 0 ? state.queue[state.queue.length - 1] : state.now_playing
  if (!added) return 'Added to the queue'
  const { title, artist } = added.track
  return artist ? `Added “${title}” – ${artist}` : `Added “${title}”`
}
