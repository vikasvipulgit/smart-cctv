import { useEffect, useRef, useState } from 'react'
import { wsUrl } from './api'

// Live events over WebSocket, with auto-reconnect and optional browser notifications.
export function useEventSocket(onEvent) {
  const [connected, setConnected] = useState(false)
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    let ws
    let ping
    let retry
    let stopped = false

    const connect = () => {
      ws = new WebSocket(wsUrl())
      ws.onopen = () => {
        setConnected(true)
        ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000)
      }
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data)
          if (data.type === 'event') {
            handler.current?.(data.event)
            notify(data.event)
          }
        } catch {}
      }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(ping)
        if (!stopped) retry = setTimeout(connect, 3000)
      }
    }
    connect()
    return () => {
      stopped = true
      clearInterval(ping)
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  return connected
}

function notify(event) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return
  const body = event.message || [event.camera_id, event.label, event.color, event.plate, event.text].filter(Boolean).join(' · ')
  new Notification(`🚨 ${event.rule_name}`, { body, icon: event.snapshot_url || '/icon.svg', tag: `event-${event.id}` })
}
