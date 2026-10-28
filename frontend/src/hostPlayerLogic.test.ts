import { describe, expect, it } from 'vitest'
import { onPlayerEvent, shouldReportPause, shouldReportPlay } from './hostPlayerLogic'

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

describe('shouldReportPause', () => {
  const base = { playerState: 2, roomPlaying: true, currentTime: 60, duration: 200 }

  it('reports a pause that stuck while the room thinks it is playing', () => {
    expect(shouldReportPause(base)).toBe(true)
  })

  it('ignores a pause that already resumed (seek / scrub)', () => {
    expect(shouldReportPause({ ...base, playerState: 1 })).toBe(false)
    expect(shouldReportPause({ ...base, playerState: 3 })).toBe(false)
  })

  it('ignores the pause the player emits right at the end of a song', () => {
    expect(shouldReportPause({ ...base, currentTime: 199.5 })).toBe(false)
  })

  it('ignores it when the room is already paused', () => {
    expect(shouldReportPause({ ...base, roomPlaying: false })).toBe(false)
  })
})

describe('shouldReportPlay', () => {
  it('reports playback started on the player while the room is paused', () => {
    expect(shouldReportPlay({ playerState: 1, roomPlaying: false })).toBe(true)
  })

  it('ignores a play that was already paused again (quick play→pause from a phone)', () => {
    expect(shouldReportPlay({ playerState: 2, roomPlaying: false })).toBe(false)
  })

  it('ignores it when the room is already playing', () => {
    expect(shouldReportPlay({ playerState: 1, roomPlaying: true })).toBe(false)
  })
})
