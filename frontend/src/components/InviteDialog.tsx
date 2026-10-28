import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { getJoinUrl, resetJoinUrl } from '../api'
import { copyText } from '../copyText'

export function InviteDialog({ onClose, onError }: { onClose: () => void; onError: (msg: string) => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    getJoinUrl().then(setUrl, (e: Error) => onError(e.message))
  }, [onError])

  useEffect(() => {
    if (url && canvasRef.current) {
      QRCode.toCanvas(canvasRef.current, url, { width: 220, margin: 1 }).catch(() => onError("Couldn't draw the QR code"))
    }
  }, [url, onError])

  const copy = async () => {
    if (!url) return
    setCopyStatus((await copyText(url)) ? 'Copied!' : "Couldn't copy — select the link and copy it manually")
  }

  const reset = async () => {
    if (!confirm('Make a new invite link? Everyone who joined with the old one will be signed out.')) return
    try {
      setUrl(await resetJoinUrl())
      setCopyStatus(null)
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Reset failed')
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <section className="dialog" role="dialog" aria-label="Invite friends" onClick={(e) => e.stopPropagation()}>
        <header className="drawer-header">
          <h2>Invite friends</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <p className="muted small">Friends on your Wi-Fi scan this to join. No password needed.</p>
        <canvas ref={canvasRef} className="qr" />
        <input className="join-url" readOnly value={url ?? 'Loading…'} onFocus={(e) => e.target.select()} />
        <div className="row">
          <button className="primary" onClick={copy} disabled={!url}>Copy link</button>
          <button className="danger" onClick={reset} disabled={!url}>Reset link</button>
        </div>
        {copyStatus ? <p className="small">{copyStatus}</p> : null}
      </section>
    </div>
  )
}
