import { describe, expect, it, vi } from 'vitest'
import { applyMessage } from './useRoom'

describe('applyMessage', () => {
  it('state messages replace the room state', () => {
    const setState = vi.fn()
    const setReady = vi.fn()
    const state = { played: [], now_playing: null, queue: [], is_playing: false, version: 3 }
    applyMessage({ type: 'state', state }, setState, setReady)
    expect(setState).toHaveBeenCalledWith(state)
    expect(setReady).not.toHaveBeenCalled()
  })

  it('ready messages update the set of downloaded songs', () => {
    const setState = vi.fn()
    const setReady = vi.fn()
    applyMessage({ type: 'ready', video_ids: ['aaaaaaaaaaa', 'bbbbbbbbbbb'] }, setState, setReady)
    expect(setReady).toHaveBeenCalledWith(new Set(['aaaaaaaaaaa', 'bbbbbbbbbbb']))
    expect(setState).not.toHaveBeenCalled()
  })

  it('ignores message types it does not know', () => {
    const setState = vi.fn()
    const setReady = vi.fn()
    applyMessage({ type: 'something-new' }, setState, setReady)
    expect(setState).not.toHaveBeenCalled()
    expect(setReady).not.toHaveBeenCalled()
  })
})
