import type { Track } from '../types'

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return ''
  const m = Math.floor(seconds / 60)
  const s = String(seconds % 60).padStart(2, '0')
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${s}` : `${m}:${s}`
}

/** Thumbnail + title/artist block shared by search results, the queue and now playing. */
export function TrackInfo({ track, addedBy }: { track: Track; addedBy?: string | null }) {
  const meta = [track.artist, formatDuration(track.duration_seconds)].filter(Boolean).join(' · ')
  return (
    <div className="track">
      {track.thumbnail_url ? (
        <img className="thumb" src={track.thumbnail_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
      ) : (
        <div className="thumb thumb-empty" aria-hidden>♪</div>
      )}
      <div className="track-text">
        <span className="track-title">{track.title}</span>
        <span className="track-meta">
          {meta}
          {addedBy ? <span className="added-by"> · added by {addedBy}</span> : null}
        </span>
      </div>
    </div>
  )
}
