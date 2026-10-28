import { describe, expect, it, vi } from 'vitest'
import { isLink, next } from './api'

describe('isLink', () => {
  it.each([
    'https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ',
    'youtu.be/dQw4w9WgXcQ',
    'dQw4w9WgXcQ',
    '  https://www.youtube.com/shorts/dQw4w9WgXcQ  ',
  ])('treats %s as a link', (text) => {
    expect(isLink(text)).toBe(true)
  })

  it.each(['daft punk', 'around the world', 'harder better', 'Evanescence', 'Tchaikovsky', 'Soundgarden'])('treats %s as a search', (text) => {
    expect(isLink(text)).toBe(false)
  })
})

describe('next', () => {
  it('marks a skip as manual so the server refocuses downloads', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response('{}', { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)
    try {
      await next('item1', true)
      await next('item2')
      const bodies = fetchMock.mock.calls.map((call: unknown[]) => JSON.parse((call[1] as RequestInit).body as string))
      expect(bodies).toEqual([
        { expected_item_id: 'item1', manual: true },
        { expected_item_id: 'item2', manual: false },
      ])
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
