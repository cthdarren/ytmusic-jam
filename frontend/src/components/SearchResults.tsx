import type { Track } from '../types'
import { TrackInfo } from './TrackInfo'

interface Props {
  results: Track[] | null
  loading: boolean
  added: Set<string>
  onAdd: (track: Track) => void
}

export function SearchResults({ results, loading, added, onAdd }: Props) {
  if (loading) return <p className="empty">Searching…</p>
  if (results === null) return <p className="empty">Find something to play, or paste a link from YouTube or YouTube Music.</p>
  if (results.length === 0) return <p className="empty">No results.</p>
  return (
    <ul className="results">
      {results.map((track) => {
        const isAdded = added.has(track.video_id)
        return (
          <li key={track.video_id} className="result-row">
            <TrackInfo track={track} />
            <button className={isAdded ? 'add added' : 'add'} onClick={() => onAdd(track)} aria-label={`Add ${track.title}`}>
              {isAdded ? '✓' : '+'}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
