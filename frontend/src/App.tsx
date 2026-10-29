import { type FormEvent, useCallback, useEffect, useState } from 'react'
import * as api from './api'
import { HostPlayer } from './components/HostPlayer'
import { InviteDialog } from './components/InviteDialog'
import { LoginScreen } from './components/LoginScreen'
import { NowPlaying } from './components/NowPlaying'
import { QueueDrawer } from './components/QueueDrawer'
import { SearchBar } from './components/SearchBar'
import { SearchResults } from './components/SearchResults'
import { TopBar } from './components/TopBar'
import { describeAdded } from './describeAdded'
import { APP_NAME, pageTitle } from './pageTitle'
import type { Role, SearchKind, Track } from './types'
import { useRoom } from './useRoom'

const NICKNAME_KEY = 'jam.nickname'

function loadNickname(): string | null {
  try {
    return localStorage.getItem(NICKNAME_KEY)
  } catch {
    return null
  }
}

function saveNickname(name: string) {
  try {
    localStorage.setItem(NICKNAME_KEY, name)
  } catch {
    // private mode etc. — the name just won't be remembered
  }
}

/** Reads and strips `?join=invalid` so a refresh doesn't repeat the message. */
function takeLoginNotice(): string | null {
  const params = new URLSearchParams(location.search)
  if (params.get('join') !== 'invalid') return null
  history.replaceState(null, '', location.pathname)
  return 'That invite link has expired — ask the host for a new one.'
}

export default function App() {
  const [role, setRole] = useState<Role | null | undefined>(undefined)
  const [notice, setNotice] = useState<string | null>(takeLoginNotice)

  useEffect(() => {
    api.me().then(setRole, () => setRole(null))
    const onUnauthorized = () => {
      setRole((prev) => {
        if (prev) setNotice('You were signed out. Guests need a fresh invite link from the host.')
        return null
      })
    }
    window.addEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  if (role === undefined) return <main className="splash">Loading…</main>
  if (role === null) return <LoginScreen notice={notice} onLoggedIn={() => setRole('owner')} />
  return <Jam role={role} onLoggedOut={() => setRole(null)} />
}

function Jam({ role, onLoggedOut }: { role: Role; onLoggedOut: () => void }) {
  const isHost = location.pathname === '/host'
  const { state, connected, ready } = useRoom()
  const [nickname, setNickname] = useState<string | null>(loadNickname)
  const [results, setResults] = useState<Track[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [added, setAdded] = useState<Set<string>>(new Set())
  const [queueOpen, setQueueOpen] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const showError = useCallback((msg: string) => setToast(msg), [])

  const title = pageTitle(state?.now_playing ?? null)
  useEffect(() => {
    document.title = title
    return () => {
      document.title = APP_NAME
    }
  }, [title])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(t)
  }, [toast])

  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    try {
      return await fn()
    } catch (e) {
      if (!(e instanceof api.ApiError && e.status === 401)) showError(e instanceof Error ? e.message : 'Something went wrong')
      return undefined
    }
  }

  const doSearch = async (q: string, kind: SearchKind) => {
    setSearching(true)
    const found = await run(() => api.search(q, kind))
    setSearching(false)
    if (found) {
      setResults(found)
      setAdded(new Set())
    }
  }

  const addTrack = async (track: Track) => {
    if (await run(() => api.addToQueue(track.video_id, nickname))) {
      setAdded((prev) => new Set(prev).add(track.video_id))
    }
  }

  const addLink = async (link: string) => {
    const added = await run(() => api.addToQueue(link, nickname))
    if (added) setToast(describeAdded(added))
    return added !== undefined
  }

  const current = state?.now_playing ?? null

  if (!nickname) return <NicknameForm onDone={(n) => { saveNickname(n); setNickname(n) }} />

  return (
    <div className="app">
      <TopBar
        role={role}
        nickname={nickname}
        isHost={isHost}
        onInvite={() => setInviteOpen(true)}
        onLogout={() => run(api.logout).then(onLoggedOut)}
      />

      {isHost ? <HostPlayer state={state} onError={showError} /> : null}

      <main className="content">
        <SearchBar busy={searching} onSearch={doSearch} onAddLink={addLink} />
        <SearchResults results={results} loading={searching} added={added} onAdd={addTrack} />
      </main>

      <NowPlaying
        state={state}
        connected={connected}
        onSkip={() => current && run(() => api.next(current.id, true))}
        onTogglePlay={() => state && run(() => api.setPlaying(!state.is_playing))}
        onOpenQueue={() => setQueueOpen(true)}
      />

      <QueueDrawer
        open={queueOpen}
        played={state?.played ?? []}
        nowPlaying={state?.now_playing ?? null}
        items={state?.queue ?? []}
        isOwner={role === 'owner'}
        onClose={() => setQueueOpen(false)}
        onRemove={(id) => run(() => api.removeItem(id))}
        onMove={(id, toIndex) => run(() => api.moveItem(id, toIndex))}
        onPlay={(id) => run(() => api.playItem(id))}
        onClear={() => run(api.clearQueue)}
        ready={ready}
      />

      {inviteOpen ? <InviteDialog onClose={() => setInviteOpen(false)} onError={showError} /> : null}
      {toast ? (
        <div className="toast" role="status" onClick={() => setToast(null)}>
          {toast}
        </div>
      ) : null}
    </div>
  )
}

function NicknameForm({ onDone }: { onDone: (name: string) => void }) {
  const [name, setName] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) onDone(name.trim().slice(0, 40))
  }
  return (
    <main className="login">
      <form className="login-card" onSubmit={submit}>
        <h1>What should we call you?</h1>
        <p className="muted small">Shown next to the songs you add.</p>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" maxLength={40} autoFocus required />
        <button className="primary" type="submit">Let's jam</button>
      </form>
    </main>
  )
}
