import type { QueueItem } from './types'

export const APP_NAME = 'YT Music Jam'

/**
 * The browser tab title, so tools like waybar can show it: "title - artist" for the song playing,
 * or "title  -  artist  |  line" while a lyric line is being sung.
 */
export function pageTitle(nowPlaying: QueueItem | null, lyric?: string | null): string {
  if (!nowPlaying) return APP_NAME
  const { title, artist } = nowPlaying.track
  if (lyric) return artist ? `${title}  -  ${artist}  |  ${lyric}` : `${title}  |  ${lyric}`
  return artist ? `${title} - ${artist}` : title
}
