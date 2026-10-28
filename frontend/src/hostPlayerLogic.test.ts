import { describe, expect, it } from 'vitest'
import {
  afterError,
  audioUrl,
  isAutoplayBlocked,
  onPlayerEvent,
  shouldReportPause,
  shouldReportPlay,
  SILENT_AUDIO,
} from './hostPlayerLogic'

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

describe('afterError', () => {
  it('skips the first couple of failures', () => {
    expect(afterError(1)).toBe('skip')
    expect(afterError(2)).toBe('skip')
  })

  it('pauses instead of draining the queue when songs keep failing', () => {
    expect(afterError(3)).toBe('pause')
    expect(afterError(10)).toBe('pause')
  })
})

describe('isAutoplayBlocked', () => {
  it('recognises the browser refusing to play without a tap', () => {
    expect(isAutoplayBlocked(new DOMException('no', 'NotAllowedError'))).toBe(true)
  })

  it('ignores interrupted loads and other errors', () => {
    expect(isAutoplayBlocked(new DOMException('replaced', 'AbortError'))).toBe(false)
    expect(isAutoplayBlocked(new Error('x'))).toBe(false)
    expect(isAutoplayBlocked(undefined)).toBe(false)
  })
})

describe('SILENT_AUDIO', () => {
  it('is a playable WAV data URI', () => {
    expect(SILENT_AUDIO.startsWith('data:audio/wav;base64,')).toBe(true)
    const bytes = atob(SILENT_AUDIO.split(',')[1])
    expect(bytes.slice(0, 4)).toBe('RIFF')
    expect(bytes.slice(8, 12)).toBe('WAVE')
  })
})
