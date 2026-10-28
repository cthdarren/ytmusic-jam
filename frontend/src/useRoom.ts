import { useEffect, useState } from 'react'
import { UNAUTHORIZED_EVENT } from './api'
import type { RoomState } from './types'

const MIN_DELAY = 1000
const MAX_DELAY = 10000

/** Live room state over the websocket, reconnecting with backoff until the session is revoked. */
export function useRoom(): { state: RoomState | null; connected: boolean } {
  const [state, setState] = useState<RoomState | null>(null)
  const [connected, setConnected] = useState(false)

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
        const msg = JSON.parse(event.data)
        if (msg.type === 'state') setState(msg.state)
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

  return { state, connected }
}
