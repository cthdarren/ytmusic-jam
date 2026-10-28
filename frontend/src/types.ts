// Mirrors backend/app/models.py — keep field names identical.

export interface Track {
  video_id: string
  title: string
  artist: string
  duration_seconds: number | null
  thumbnail_url: string | null
}

export interface QueueItem {
  id: string
  track: Track
  added_by: string | null
}

export interface RoomState {
  now_playing: QueueItem | null
  queue: QueueItem[]
  is_playing: boolean
  version: number
}

export type Role = 'owner' | 'guest'

export type SearchKind = 'songs' | 'videos'
