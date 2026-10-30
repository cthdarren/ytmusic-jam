import type { Lyrics, Role, RoomState, SearchKind, Track } from './types'

/** Fired on window when the session is gone (401 or websocket close 4401). */
export const UNAUTHORIZED_EVENT = 'jam:unauthorized'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/

/**
 * True when the search box holds a YouTube or Spotify link, or a bare video id, rather than a
 * search query.
 * A bare 11-char token only counts if it has a digit, `_` or `-`, so one-word searches like
 * "Evanescence" stay searches.
 */
export function isLink(text: string): boolean {
  const t = text.trim()
  return (
    t.includes('youtube.com/') ||
    t.includes('youtu.be/') ||
    t.includes('open.spotify.com/') ||
    t.startsWith('spotify:') ||
    (VIDEO_ID.test(t) && /[0-9_-]/.test(t))
  )
}

async function request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? 'GET',
    credentials: 'same-origin',
    headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  })
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') detail = data.detail
    } catch {
      // non-JSON error body; keep statusText
    }
    if (res.status === 401 && !path.startsWith('/api/auth/')) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export async function me(): Promise<Role | null> {
  try {
    return (await request<{ role: Role }>('/api/auth/me')).role
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    throw e
  }
}

export const login = (username: string, password: string) =>
  request<{ role: Role }>('/api/auth/login', { method: 'POST', body: { username, password } })

export const logout = () => request<void>('/api/auth/logout', { method: 'POST' })

/** The invite link, plus the Telegram bot's deep link when the bot is running. */
export interface JoinLinks {
  url: string
  telegram_url?: string
}

export const getJoinUrl = () => request<JoinLinks>('/api/join')

export const resetJoinUrl = () => request<JoinLinks>('/api/join/reset', { method: 'POST' })

export const search = (q: string, kind: SearchKind = 'songs') =>
  request<Track[]>(`/api/search?${new URLSearchParams({ q, kind })}`)

export const addToQueue = (input: string, addedBy: string | null) =>
  request<RoomState>('/api/queue', { method: 'POST', body: { input, added_by: addedBy } })

export const removeItem = (id: string) =>
  request<RoomState>(`/api/queue/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const moveItem = (id: string, toIndex: number) =>
  request<RoomState>(`/api/queue/${encodeURIComponent(id)}/move`, { method: 'POST', body: { to_index: toIndex } })

export const playItem = (id: string) =>
  request<RoomState>(`/api/queue/${encodeURIComponent(id)}/play`, { method: 'POST' })

export const clearQueue = () => request<RoomState>('/api/queue/clear', { method: 'POST' })

/** `manual` = someone pressed Skip (the host's own "song ended" is not manual). */
export const next = (expectedItemId: string | null, manual = false) =>
  request<RoomState>('/api/player/next', { method: 'POST', body: { expected_item_id: expectedItemId, manual } })

export const setPlaying = (playing: boolean) =>
  request<RoomState>('/api/player/playing', { method: 'POST', body: { playing } })

/** Timed lyrics for a song in the jam (empty when none were found or lyrics are turned off). */
export const getLyrics = (videoId: string) => request<Lyrics>(`/api/lyrics/${videoId}`)
