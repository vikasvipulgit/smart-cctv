import { useEffect, useState } from 'react'
import { api } from '../api'
import EventCard from './EventCard.jsx'

const PAGE = 24

export default function EventsPage({ liveEvents }) {
  const [filters, setFilters] = useState({ camera: '', label: '', unacknowledged: false })
  const [data, setData] = useState({ total: 0, items: [] })
  const [offset, setOffset] = useState(0)
  const [cameras, setCameras] = useState([])

  useEffect(() => { api.cameras().then(setCameras).catch(() => {}) }, [])

  useEffect(() => {
    const params = { limit: PAGE, offset }
    if (filters.camera) params.camera = filters.camera
    if (filters.label) params.label = filters.label
    if (filters.unacknowledged) params.unacknowledged = true
    api.events(params).then(setData).catch(() => {})
  }, [filters, offset, liveEvents.length])

  const set = (k, v) => { setOffset(0); setFilters((f) => ({ ...f, [k]: v })) }

  return (
    <div>
      <div className="toolbar">
        <h2>Events <span className="muted">({data.total})</span></h2>
        <select value={filters.camera} onChange={(e) => set('camera', e.target.value)}>
          <option value="">All cameras</option>
          {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={filters.label} onChange={(e) => set('label', e.target.value)}>
          <option value="">All objects</option>
          {['person', 'car', 'truck', 'bus', 'motorcycle', 'bicycle'].map((l) => <option key={l}>{l}</option>)}
        </select>
        <label className="check">
          <input type="checkbox" checked={filters.unacknowledged} onChange={(e) => set('unacknowledged', e.target.checked)} />
          Open only
        </label>
      </div>

      <div className="event-grid">
        {data.items.map((e) => <EventCard key={e.id} event={e} />)}
      </div>
      {data.items.length === 0 && <p className="muted">No events match.</p>}

      <div className="pager">
        <button className="btn ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Newer</button>
        <span className="muted">{data.total ? `${offset + 1}-${Math.min(offset + PAGE, data.total)} of ${data.total}` : ''}</span>
        <button className="btn ghost" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Older →</button>
      </div>
    </div>
  )
}
