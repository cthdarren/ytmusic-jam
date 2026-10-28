import type { RoomState } from '../types'
import { TrackInfo } from './TrackInfo'

interface Props {
  state: RoomState | null
  connected: boolean
  onSkip: () => void
  onTogglePlay: () => void
  onOpenQueue: () => void
}

export function NowPlaying({ state, connected, onSkip, onTogglePlay, onOpenQueue }: Props) {
  const current = state?.now_playing
  return (
    <footer className="now-playing">
      {!connected ? <div className="offline">Reconnecting…</div> : null}
      <div className="now-playing-inner">
        {current ? <TrackInfo track={current.track} addedBy={current.added_by} /> : <span className="muted">Nothing playing</span>}
        <div className="controls">
          <button className="icon-btn big" onClick={onTogglePlay} disabled={!current} aria-label={state?.is_playing ? 'Pause' : 'Play'}>
            {state?.is_playing ? '❚❚' : '▶'}
          </button>
          <button className="icon-btn big" onClick={onSkip} disabled={!current} aria-label="Skip">
            ⏭
          </button>
          <button className="queue-btn" onClick={onOpenQueue}>
            Queue ({state?.queue.length ?? 0})
          </button>
        </div>
      </div>
    </footer>
  )
}
