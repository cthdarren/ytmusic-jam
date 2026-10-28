import { describe, expect, it } from 'vitest'
import { isLink } from './api'

describe('isLink', () => {
  it.each([
    'https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ',
    'youtu.be/dQw4w9WgXcQ',
    'dQw4w9WgXcQ',
    '  https://www.youtube.com/shorts/dQw4w9WgXcQ  ',
  ])('treats %s as a link', (text) => {
    expect(isLink(text)).toBe(true)
  })

  it.each(['daft punk', 'around the world', 'harder better'])('treats %s as a search', (text) => {
    expect(isLink(text)).toBe(false)
  })
})
