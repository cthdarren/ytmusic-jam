import { useState } from 'react'
import type { Role } from '../types'
import { ConfirmDialog } from './ConfirmDialog'

interface Props {
  role: Role
  nickname: string
  isHost: boolean
  onInvite: () => void
  onLogout: () => void
}

/**
 * Title bar with the session controls. Everyone can log out (e.g. a guest who is taking
 * over as host); guests confirm first, since they can only get back in with an invite.
 */
export function TopBar({ role, nickname, isHost, onInvite, onLogout }: Props) {
  const [confirmingLogout, setConfirmingLogout] = useState(false)

  return (
    <header className="topbar">
      <h1>YT Music Jam</h1>
      <div className="topbar-actions">
        {role === 'owner' ? (
          <>
            <button onClick={onInvite}>Invite</button>
            {isHost ? null : <a className="button" href="/host">Open player</a>}
            <button onClick={onLogout}>Log out</button>
          </>
        ) : (
          <>
            <span className="muted small">Jamming as {nickname}</span>
            <button onClick={() => setConfirmingLogout(true)}>Log out</button>
          </>
        )}
      </div>
      {confirmingLogout ? (
        <ConfirmDialog
          title="Log out?"
          message="You'll need the invite link or QR code to rejoin. The host can sign in after logging out."
          confirmLabel="Log out"
          onCancel={() => setConfirmingLogout(false)}
          onConfirm={() => {
            setConfirmingLogout(false)
            onLogout()
          }}
        />
      ) : null}
    </header>
  )
}
