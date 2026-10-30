import { useEffect } from 'react'
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

/**
 * Keeps document.title on `title` while mounted, and puts the app name back on unmount. The title
 * changes with every lyric line, so it goes straight to the new one: never via the app name,
 * which a status bar would show as a flash.
 */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title
  }, [title])
  useEffect(
    () => () => {
      document.title = APP_NAME
    },
    [],
  )
}
