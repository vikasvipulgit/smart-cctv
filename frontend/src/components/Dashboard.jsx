import { useEffect, useState } from 'react'
import { api } from '../api'
import EventCard from './EventCard.jsx'

export default function Dashboard({ liveEvents, onClearAlerts }) {
  const [cameras, setCameras] = useState([])
  const [recent, setRecent] = useState([])
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [clearing, setClearing] = useState(false)
  const [clearedBefore, setClearedBefore] = useState(0) // live events with id <= this were cleared

  const load = () =>
      Promise.all([api.cameras(), api.events({ limit: 12, unacknowledged: true }), api.stats()])
        .then(([c, e, s]) => {
          setCameras(c)
          setRecent(e.items)
          setStats(s)
          setError(null)
        })
        .catch((err) => setError(err.message))

  useEffect(() => {
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [])

  const clearAlerts = async () => {
    setClearing(true)
    try {
      await api.ackAllEvents()
      setClearedBefore(Math.max(clearedBefore, ...liveEvents.map((e) => e.id), ...recent.map((e) => e.id)))
      setRecent([])
      onClearAlerts?.()
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setClearing(false)
    }
  }

  // merge live websocket events in front of the loaded list (open alerts only)
  const ids = new Set()
  const events = [...liveEvents, ...recent]
    .filter((e) => e.id > clearedBefore && !e.acknowledged)
    .filter((e) => (ids.has(e.id) ? false : ids.add(e.id)))
    .slice(0, 12)

  return (
    <div className="dashboard">
      {error && <div className="banner error">Cannot reach the backend ({error}). Is it running on port 8000?</div>}

      <section className="stats">
        <div className="stat"><span>{cameras.filter((c) => c.connected).length}/{cameras.filter((c) => c.enabled).length}</span>cameras online</div>
        <div className="stat"><span>{stats?.unacknowledged ?? '-'}</span>open alerts</div>
        <div className="stat"><span>{Object.values(stats?.by_label || {}).reduce((a, b) => a + b, 0)}</span>events total</div>
      </section>

      <div className="dash-grid">
        <section>
          <h2>Live cameras</h2>
          <div className="camera-grid">
            {cameras.filter((cam) => cam.enabled).map((cam) => (
              <div className="camera-tile" key={cam.id}>
                <div className="camera-head">
                  <span className={`dot ${cam.connected ? 'ok' : 'bad'}`} />
                  <strong>{cam.name}</strong>
                  <span className="muted small">{cam.processing_fps} fps</span>
                </div>
                {cam.enabled && cam.connected ? (
                  <img className="live" src={api.streamUrl(cam.id)} alt={`${cam.name} live`} />
                ) : (
                  <div className="live offline">{cam.error || 'Connecting...'}</div>
                )}
              </div>
            ))}
            {cameras.length === 0 && !error && <p className="muted">No cameras configured. See the Cameras page.</p>}
            {cameras.length > 0 && !cameras.some((c) => c.enabled) && (
              <p className="muted">All cameras are off. Turn one on from the <a href="#/cameras">Cameras</a> page.</p>
            )}
          </div>
        </section>

        <aside>
          <div className="toolbar alerts-head">
            <h2>Latest alerts</h2>
            <button className="btn small ghost" onClick={clearAlerts} disabled={clearing || events.length === 0}
              title="Mark all open alerts as seen. They stay in the Events history.">
              {clearing ? 'Clearing...' : 'Clear alerts'}
            </button>
          </div>
          <div className="event-list">
            {events.map((e) => <EventCard key={e.id} event={e} compact />)}
            {events.length === 0 && <p className="muted">No open alerts.</p>}
          </div>
          <a href="#/events" className="more">All events →</a>
        </aside>
      </div>
    </div>
  )
}
