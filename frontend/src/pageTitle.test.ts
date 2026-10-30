import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { pageTitle, useDocumentTitle } from './pageTitle'
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

  it('adds the line being sung as "title  -  artist  |  line"', () => {
    expect(pageTitle(item('비올레타 Violeta', 'IZ*ONE'), '꿈을 꾸는 듯해')).toBe('비올레타 Violeta  -  IZ*ONE  |  꿈을 꾸는 듯해')
  })

  it('leaves out a missing artist next to a line', () => {
    expect(pageTitle(item('Some Video', ''), 'la la')).toBe('Some Video  |  la la')
  })

  it('keeps "title - artist" when there is no line', () => {
    expect(pageTitle(item('X', 'Y'), null)).toBe('X - Y')
    expect(pageTitle(item('X', 'Y'), '')).toBe('X - Y')
  })

  it('ignores a line when nothing is playing', () => {
    expect(pageTitle(null, 'stray')).toBe('YT Music Jam')
  })
})

describe('useDocumentTitle', () => {
  it('changes the title straight to the next one, without flashing the app name in between', () => {
    const { rerender, unmount } = renderHook(({ title }) => useDocumentTitle(title), { initialProps: { title: 'A  -  B  |  one' } })
    const set = vi.spyOn(document, 'title', 'set')
    try {
      rerender({ title: 'A  -  B  |  two' })
      expect(set.mock.calls).toEqual([['A  -  B  |  two']])
      unmount()
      expect(set.mock.lastCall).toEqual(['YT Music Jam'])
    } finally {
      set.mockRestore()
    }
  })
})
