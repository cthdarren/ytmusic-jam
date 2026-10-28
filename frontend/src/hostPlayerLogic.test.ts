import { describe, expect, it } from 'vitest'
import { onPlayerEvent } from './hostPlayerLogic'

describe('onPlayerEvent', () => {
  it('advances when a song ends', () => {
    expect(onPlayerEvent({ kind: 'ended' }, 'x')).toEqual({ call: 'next', expected: 'x' })
  })

  it.each([2, 5, 100, 101, 150])('skips unplayable videos (error %i)', (code) => {
    expect(onPlayerEvent({ kind: 'error', code }, 'x')).toEqual({ call: 'next', expected: 'x' })
  })

  it('ignores unknown errors', () => {
    expect(onPlayerEvent({ kind: 'error', code: 999 }, 'x')).toBeNull()
  })

  it('does nothing when nothing is playing', () => {
    expect(onPlayerEvent({ kind: 'ended' }, null)).toBeNull()
    expect(onPlayerEvent({ kind: 'error', code: 150 }, null)).toBeNull()
  })
})
