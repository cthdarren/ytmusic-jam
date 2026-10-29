import { describe, expect, it } from 'vitest'
import { describeAdded } from './describeAdded'
import type { QueueItem, RoomState } from './types'

const item = (title: string, artist: string): QueueItem => ({
  id: title,
  added_by: null,
  track: { video_id: 'aaaaaaaaaaa', title, artist, duration_seconds: 200, thumbnail_url: null },
})
const state = (now: QueueItem | null, queue: QueueItem[]): RoomState => ({
  played: [],
  now_playing: now,
  queue,
  is_playing: true,
  version: 1,
})

describe('describeAdded', () => {
  it('names the song added to the end of the queue', () => {
    expect(describeAdded(state(item('A', 'X'), [item('B', 'Y'), item('Shape of You', 'Ed Sheeran')]))).toBe(
      'Added “Shape of You” – Ed Sheeran',
    )
  })

  it('names the song that started playing when the queue was empty', () => {
    expect(describeAdded(state(item('Blinding Lights', 'The Weeknd'), []))).toBe('Added “Blinding Lights” – The Weeknd')
  })

  it('falls back to a plain message', () => {
    expect(describeAdded(state(null, []))).toBe('Added to the queue')
  })
})
