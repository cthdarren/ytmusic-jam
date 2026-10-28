import { describe, expect, it } from 'vitest'
import { audioUrl, onPlayerEvent, shouldReportPause, shouldReportPlay } from './hostPlayerLogic'

describe('onPlayerEvent', () => {
  it('advances when a song ends', () => {
    expect(onPlayerEvent({ kind: 'ended' }, 'x')).toEqual({ call: 'next', expected: 'x' })
  })

  it('skips a song the server could not get', () => {
    expect(onPlayerEvent({ kind: 'error' }, 'x')).toEqual({ call: 'next', expected: 'x' })
  })

  it('does nothing when nothing is playing', () => {
    expect(onPlayerEvent({ kind: 'ended' }, null)).toBeNull()
    expect(onPlayerEvent({ kind: 'error' }, null)).toBeNull()
  })
})

describe('shouldReportPause', () => {
  const base = { paused: true, roomPlaying: true, currentTime: 60, duration: 200 }

  it('reports a pause that stuck while the room thinks it is playing', () => {
    expect(shouldReportPause(base)).toBe(true)
  })

  it('ignores a pause that already resumed (seek)', () => {
    expect(shouldReportPause({ ...base, paused: false })).toBe(false)
  })

  it('ignores the pause <audio> fires right before ended', () => {
    expect(shouldReportPause({ ...base, currentTime: 199.5 })).toBe(false)
    expect(shouldReportPause({ ...base, currentTime: 200 })).toBe(false)
  })

  it('still reports when the duration is not known yet', () => {
    expect(shouldReportPause({ ...base, duration: NaN })).toBe(true)
  })

  it('ignores it when the room is already paused', () => {
    expect(shouldReportPause({ ...base, roomPlaying: false })).toBe(false)
  })
})

describe('shouldReportPlay', () => {
  it('reports playback started on the host while the room is paused', () => {
    expect(shouldReportPlay({ paused: false, roomPlaying: false })).toBe(true)
  })

  it('ignores a play that was already paused again', () => {
    expect(shouldReportPlay({ paused: true, roomPlaying: false })).toBe(false)
  })

  it('ignores it when the room is already playing', () => {
    expect(shouldReportPlay({ paused: false, roomPlaying: true })).toBe(false)
  })
})

describe('audioUrl', () => {
  it('points at the server audio endpoint', () => {
    expect(audioUrl('AfeV_OZmHvM')).toBe('/api/audio/AfeV_OZmHvM')
  })
})
