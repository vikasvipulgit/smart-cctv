import { useCallback, useEffect, useState } from 'react'
import { useEventSocket } from './useEventSocket'
import Dashboard from './components/Dashboard.jsx'
import EventsPage from './components/EventsPage.jsx'
import SearchPage from './components/SearchPage.jsx'
import RulesPage from './components/RulesPage.jsx'
import CamerasPage from './components/CamerasPage.jsx'
import ZoneEditor from './components/ZoneEditor.jsx'
import EventModal from './components/EventModal.jsx'

const PAGES = [
  { id: 'dashboard', label: 'Live' },
  { id: 'events', label: 'Events' },
  { id: 'search', label: 'Ask AI' },
  { id: 'rules', label: 'Rules' },
  { id: 'cameras', label: 'Cameras' },
]

// Simple hash routing: #/events, #/events/12, #/search ...
function useHashRoute() {
  const parse = () => {
    const [, page = 'dashboard', id] = window.location.hash.split('/')
    return { page: PAGES.some((p) => p.id === page) ? page : 'dashboard', id }
  }
  const [route, setRoute] = useState(parse)
  useEffect(() => {
    const onChange = () => setRoute(parse())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

export default function App() {
  const route = useHashRoute()
  const [liveEvents, setLiveEvents] = useState([])
  const [toasts, setToasts] = useState([])
  const [notifPermission, setNotifPermission] = useState(typeof Notification !== 'undefined' ? Notification.permission : 'unsupported')

  const onEvent = useCallback((ev) => {
    setLiveEvents((prev) => [ev, ...prev].slice(0, 50))
    setToasts((prev) => [...prev, ev].slice(-3))
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== ev.id)), 6000)
  }, [])
  const connected = useEventSocket(onEvent)

  const clearAlerts = useCallback(() => {
    setLiveEvents([])
    setToasts([])
  }, [])

  const enableNotifications = async () => {
    const p = await Notification.requestPermission()
    setNotifPermission(p)
  }

  const openEventId = route.page === 'events' && route.id ? Number(route.id) : null

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/icon.svg" alt="" width="28" height="28" />
          <span>Smart CCTV</span>
        </div>
        <nav>
          {PAGES.map((p) => (
            <a key={p.id} href={`#/${p.id}`} className={route.page === p.id ? 'active' : ''}>
              {p.label}
            </a>
          ))}
        </nav>
        <div className="status">
          {notifPermission === 'default' && (
            <button className="btn small ghost" onClick={enableNotifications}>Enable alerts</button>
          )}
          <span className={`dot ${connected ? 'ok' : 'bad'}`} title={connected ? 'Live alerts connected' : 'Reconnecting...'} />
          <span className="muted">{connected ? 'Live' : 'Offline'}</span>
        </div>
      </header>

      <main>
        {route.page === 'dashboard' && <Dashboard liveEvents={liveEvents} onClearAlerts={clearAlerts} />}
        {route.page === 'events' && <EventsPage liveEvents={liveEvents} />}
        {route.page === 'search' && <SearchPage />}
        {route.page === 'rules' && <RulesPage />}
        {route.page === 'cameras' && !route.id && <CamerasPage />}
        {route.page === 'cameras' && route.id && <ZoneEditor key={route.id} cameraId={decodeURIComponent(route.id)} />}
      </main>

      {openEventId && <EventModal eventId={openEventId} onClose={() => (window.location.hash = '#/events')} />}

      <div className="toasts">
        {toasts.map((t) => (
          <a key={t.id} className="toast" href={`#/events/${t.id}`}>
            {t.snapshot_url && <img src={t.snapshot_url} alt="" />}
            <div>
              <strong>{t.rule_name}</strong>
              <div className="muted">{t.message || [t.camera_id, t.label, t.color, t.plate, t.text].filter(Boolean).join(' · ')}</div>
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
