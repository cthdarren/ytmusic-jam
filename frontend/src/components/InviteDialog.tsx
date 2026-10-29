import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { getJoinUrl, type JoinLinks, resetJoinUrl } from '../api'
import { copyText } from '../copyText'

export function InviteDialog({ onClose, onError }: { onClose: () => void; onError: (msg: string) => void }) {
  const [links, setLinks] = useState<JoinLinks | null>(null)
  // What the QR code and Copy button share: the web invite, or the Telegram bot's join link.
  const [via, setVia] = useState<'web' | 'telegram'>('web')
  const telegramUrl = links?.telegram_url ?? null
  const url = (via === 'telegram' && telegramUrl) || links?.url || null
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    getJoinUrl().then(setLinks, (e: Error) => onError(e.message))
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
      setLinks(await resetJoinUrl())
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
        {telegramUrl ? (
          <div className="tabs" role="tablist">
            {(['web', 'telegram'] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={via === v}
                className={via === v ? 'tab active' : 'tab'}
                onClick={() => {
                  setVia(v)
                  setCopyStatus(null)
                }}
              >
                {v === 'web' ? 'Web' : 'Telegram'}
              </button>
            ))}
          </div>
        ) : null}
        <p className="muted small">
          {via === 'telegram' && telegramUrl
            ? 'Friends scan this to add songs from Telegram by sending the bot links.'
            : 'Friends on your Wi-Fi scan this to join. No password needed.'}
        </p>
        <canvas ref={canvasRef} className="qr" />
        <input className="join-url" readOnly value={url ?? 'Loading…'} onFocus={(e) => e.target.select()} />
        <div className="row">
          <button className="primary" onClick={copy} disabled={!url}>Copy link</button>
          <button className="danger" onClick={reset} disabled={!url}>Reset link</button>
        </div>
        {copyStatus ? <p className="small">{copyStatus}</p> : null}
        {via === 'telegram' && telegramUrl ? (
          <a className="small" href={telegramUrl} target="_blank" rel="noreferrer">
            Open in Telegram (to add your own account)
          </a>
        ) : null}
      </section>
    </div>
  )
}
