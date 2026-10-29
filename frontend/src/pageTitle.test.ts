import { describe, expect, it } from 'vitest'
import { pageTitle } from './pageTitle'
import type { QueueItem } from './types'

const item = (title: string, artist: string): QueueItem => ({
  id: 'x',
  added_by: null,
  track: { video_id: 'aaaaaaaaaaa', title, artist, duration_seconds: 200, thumbnail_url: null },
})

describe('pageTitle', () => {
  it('shows the song playing as "title - artist"', () => {
    expect(pageTitle(item('비올레타 Violeta', 'IZ*ONE'))).toBe('비올레타 Violeta - IZ*ONE')
  })

  it('falls back to the app name when nothing is playing', () => {
    expect(pageTitle(null)).toBe('YT Music Jam')
  })

  it('leaves out a missing artist', () => {
    expect(pageTitle(item('Some Video', ''))).toBe('Some Video')
  })
})
