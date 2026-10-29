import { type FormEvent, useState } from 'react'
import { isLink } from '../api'
import type { SearchKind } from '../types'

interface Props {
  busy: boolean
  onSearch: (query: string, kind: SearchKind) => void
  onAddLink: (link: string) => Promise<boolean>
}

/** One box for both: a YouTube link goes straight into the queue, anything else is a search. */
export function SearchBar({ busy, onSearch, onAddLink }: Props) {
  const [text, setText] = useState('')
  const [kind, setKind] = useState<SearchKind>('songs')
  const linkMode = isLink(text)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const value = text.trim()
    if (!value) return
    if (linkMode) {
      if (await onAddLink(value)) setText('')
    } else {
      onSearch(value, kind)
    }
  }

  const changeKind = (k: SearchKind) => {
    setKind(k)
    if (text.trim() && !linkMode) onSearch(text.trim(), k)
  }

  return (
    <form className="search" onSubmit={submit}>
      <div className="search-row">
        <input
          type="search"
          enterKeyHint={linkMode ? 'done' : 'search'}
          placeholder="Search songs or paste a YouTube or Spotify link"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Search or paste link"
        />
        <button className="primary" type="submit" disabled={busy || !text.trim()}>
          {linkMode ? 'Add' : 'Search'}
        </button>
      </div>
      <div className="tabs" role="tablist">
        {(['songs', 'videos'] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            className={kind === k ? 'tab active' : 'tab'}
            onClick={() => changeKind(k)}
          >
            {k === 'songs' ? 'Songs' : 'Videos'}
          </button>
        ))}
      </div>
    </form>
  )
}
