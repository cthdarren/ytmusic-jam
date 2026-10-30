import { fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LyricLine, RoomState } from '../types'
import { HostPlayer } from './HostPlayer'

const LINES: LyricLine[] = [
  { start_ms: 1000, text: 'first' },
  { start_ms: 5000, text: 'second' },
]

const playing = (videoId: string): RoomState => ({
  played: [],
  now_playing: {
    id: `item-${videoId}`,
    added_by: null,
    track: { video_id: videoId, title: 'Song', artist: 'Singer', duration_seconds: 200, thumbnail_url: null },
  },
  queue: [],
  is_playing: true,
  version: 1,
})

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

/** Answers /api/lyrics/<id> from `answers`; a missing id hangs until `release(id, lines)`. */
function stubLyrics(answers: Record<string, LyricLine[]>) {
  const pending: Record<string, (r: Response) => void> = {}
  const fetchMock = vi.fn((url: string) => {
    const id = url.split('/').pop()!
    if (id in answers) return Promise.resolve(json({ lines: answers[id] }))
    return new Promise<Response>((resolve) => {
      pending[id] = resolve
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, release: (id: string, lines: LyricLine[]) => pending[id](json({ lines })) }
}

/** Moves the player to `seconds` (playing unless `paused`) and fires timeupdate. */
function tick(audio: HTMLAudioElement, seconds: number, paused = false) {
  Object.defineProperty(audio, 'currentTime', { value: seconds, configurable: true })
  Object.defineProperty(audio, 'paused', { value: paused, configurable: true })
  fireEvent.timeUpdate(audio)
}

function renderPlayer(state: RoomState) {
  const onLyric = vi.fn()
  const utils = render(<HostPlayer state={state} onError={vi.fn()} onLyric={onLyric} />)
  const audio = utils.container.querySelector('audio')!
  return { ...utils, audio, onLyric, last: () => onLyric.mock.lastCall?.[0] }
}

describe('HostPlayer lyrics', () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('reports the line being sung', async () => {
    const { fetchMock } = stubLyrics({ aaaaaaaaaaa: LINES })
    const { audio, last } = renderPlayer(playing('aaaaaaaaaaa'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/lyrics/aaaaaaaaaaa', expect.anything()))
    await waitFor(() => {
      tick(audio, 6)
      expect(last()).toBe('second')
    })
  })

  it('follows a seek back', async () => {
    stubLyrics({ aaaaaaaaaaa: LINES })
    const { audio, last } = renderPlayer(playing('aaaaaaaaaaa'))
    await waitFor(() => {
      tick(audio, 6)
      expect(last()).toBe('second')
    })
    tick(audio, 2)
    expect(last()).toBe('first')
  })

  it('reports no line while paused', async () => {
    stubLyrics({ aaaaaaaaaaa: LINES })
    const { audio, last } = renderPlayer(playing('aaaaaaaaaaa'))
    await waitFor(() => {
      tick(audio, 6)
      expect(last()).toBe('second')
    })
    fireEvent.pause(audio)
    expect(last()).toBeNull()
    tick(audio, 6, true)
    expect(last()).toBeNull()
  })

  it('reports no line before the first line', async () => {
    stubLyrics({ aaaaaaaaaaa: LINES })
    const { audio, last, onLyric } = renderPlayer(playing('aaaaaaaaaaa'))
    await waitFor(() => {
      tick(audio, 2)
      expect(last()).toBe('first')
    })
    onLyric.mockClear()
    tick(audio, 0.5)
    expect(last()).toBeNull()
    expect(onLyric).toHaveBeenCalled()
  })

  it('ignores lyrics that arrive for a song that is no longer playing', async () => {
    const { fetchMock, release } = stubLyrics({ bbbbbbbbbbb: [] })
    const { audio, last, rerender, onLyric } = renderPlayer(playing('aaaaaaaaaaa'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    rerender(<HostPlayer state={playing('bbbbbbbbbbb')} onError={vi.fn()} onLyric={onLyric} />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    release('aaaaaaaaaaa', LINES)
    await new Promise((r) => setTimeout(r, 0))
    tick(audio, 6)
    expect(last()).toBeNull()
  })
})
