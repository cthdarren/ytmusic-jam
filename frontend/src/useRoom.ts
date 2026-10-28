import { useEffect, useState } from 'react'
import { UNAUTHORIZED_EVENT } from './api'
import type { RoomState } from './types'

const MIN_DELAY = 1000
const MAX_DELAY = 10000

/**
 * Apply one server message: "state" is the room, "ready" lists the songs already downloaded
 * on the server (they start instantly). Unknown types are ignored so the server can add more.
 */
export function applyMessage(
  msg: { type: string; state?: RoomState; video_ids?: string[] },
  setState: (state: RoomState) => void,
  setReady: (ready: Set<string>) => void,
): void {
  if (msg.type === 'state' && msg.state) setState(msg.state)
  else if (msg.type === 'ready' && msg.video_ids) setReady(new Set(msg.video_ids))
}

/** Live room state over the websocket, reconnecting with backoff until the session is revoked. */
export function useRoom(): { state: RoomState | null; connected: boolean; ready: Set<string> } {
  const [state, setState] = useState<RoomState | null>(null)
  const [connected, setConnected] = useState(false)
  const [ready, setReady] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let delay = MIN_DELAY
    let stopped = false

    const connect = () => {
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${scheme}://${location.host}/ws`)
      ws.onopen = () => {
        setConnected(true)
        delay = MIN_DELAY
      }
      ws.onmessage = (event) => {
        applyMessage(JSON.parse(event.data), setState, setReady)
      }
      ws.onclose = (event) => {
        setConnected(false)
        if (stopped) return
        if (event.code === 4401) {
          window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
          return
        }
        timer = setTimeout(connect, delay)
        delay = Math.min(delay * 2, MAX_DELAY)
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      ws?.close()
    }
  }, [])

  return { state, connected, ready }
}
