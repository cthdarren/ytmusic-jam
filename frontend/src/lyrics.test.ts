import { describe, expect, it } from 'vitest'
import { currentLine } from './lyrics'

const lines = [
  { start_ms: 5000, text: 'A' },
  { start_ms: 8000, text: 'B' },
]

describe('currentLine', () => {
  it('has no line before the first one starts', () => {
    expect(currentLine(lines, 4999)).toBeNull()
  })

  it('shows a line from the moment it starts', () => {
    expect(currentLine(lines, 5000)).toBe('A')
  })

  it('keeps the last line until the next one starts', () => {
    expect(currentLine(lines, 7999)).toBe('A')
  })

  it('keeps the final line to the end', () => {
    expect(currentLine(lines, 60000)).toBe('B')
  })

  it('has no line without lyrics', () => {
    expect(currentLine([], 1000)).toBeNull()
  })
})
