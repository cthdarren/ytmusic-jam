import type { QueueItem } from './types'

export const APP_NAME = 'YT Music Jam'

/** The browser tab title: "title - artist" for the song playing, so tools like waybar can show it. */
export function pageTitle(nowPlaying: QueueItem | null): string {
  if (!nowPlaying) return APP_NAME
  const { title, artist } = nowPlaying.track
  return artist ? `${title} - ${artist}` : title
}
