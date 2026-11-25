import { useEffect, useState } from 'react'
import { api, formatTime, mediaUrl } from '../api'
import EventCard from './EventCard.jsx'

const EXAMPLES = [
  'white car in gate area today',
  'people after 8 pm yesterday',
  'trucks in the last 2 hours',
  'Alert me on telegram if anyone is in gate area after midnight',
]

const isAlertPrompt = (text) => /\b(alert|notify|tell|warn)\b/i.test(text)

export default function SearchPage() {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [proposal, setProposal] = useState(null)
  const [message, setMessage] = useState(null)
  const [caps, setCaps] = useState(null)

  useEffect(() => { api.capabilities().then(setCaps).catch(() => {}) }, [])

  const run = async (text) => {
    const p = (text ?? prompt).trim()
    if (!p) return
    setPrompt(p)
    setLoading(true)
    setMessage(null)
    setResult(null)
    setProposal(null)
    try {
      if (isAlertPrompt(p)) setProposal(await api.proposeRule(p))
      else setResult(await api.search(p))
    } catch (err) {
      setMessage({ error: true, text: err.message })
    } finally {
      setLoading(false)
    }
  }

  const saveRule = async () => {
    try {
      await api.createRule(proposal)
      setMessage({ error: false, text: `Alert "${proposal.name}" is now live. Manage it on the Rules page.` })
      setProposal(null)
    } catch (err) {
      setMessage({ error: true, text: err.message })
    }
  }

  const f = result?.filters
  const chips = f
    ? [
        ...f.labels.map((x) => `object: ${x}`),
        ...f.colors.map((x) => `colour: ${x}`),
        ...f.cameras.map((x) => `camera: ${x}`),
        ...f.zones.map((x) => `zone: ${x}`),
        f.plate && `plate: ${f.plate}`,
        f.since && `from ${formatTime(f.since)}`,
        f.until && `until ${formatTime(f.until)}`,
        f.hour_from != null && `after ${f.hour_from}:00`,
        f.hour_to != null && `before ${f.hour_to}:00`,
      ].filter(Boolean)
    : []

  return (
    <div className="search">
      <h2>Ask AI</h2>
      <p className="muted">
        Search footage in plain words, or start with "Alert me..." to create a new live alert.
        {caps && !caps.llm_ready && ' (Using the built-in keyword parser. Set LLM_PROVIDER in .env for smarter understanding.)'}
      </p>

      <form className="prompt-box" onSubmit={(e) => { e.preventDefault(); run() }}>
        <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. show every white car at the gate yesterday after 6 pm" autoFocus />
        <button className="btn" disabled={loading}>{loading ? 'Thinking...' : 'Go'}</button>
      </form>
      <div className="examples">
        {EXAMPLES.map((ex) => <button key={ex} className="chip" onClick={() => run(ex)}>{ex}</button>)}
      </div>

      {message && <div className={`banner ${message.error ? 'error' : 'success'}`}>{message.text}</div>}

      {proposal && (
        <div className="card proposal">
          <h3>Confirm this alert</h3>
          <p className="muted">Check that the system understood you correctly before it goes live.</p>
          <dl className="details">
            <dt>Name</dt><dd>{proposal.name}</dd>
            <dt>Objects</dt><dd>{proposal.classes.join(', ') || 'any'}</dd>
            <dt>Zone</dt><dd>{proposal.zone || 'whole frame'}</dd>
            <dt>Cameras</dt><dd>{proposal.cameras.join(', ') || 'all'}</dd>
            {proposal.colors.length > 0 && (<><dt>Colours</dt><dd>{proposal.colors.join(', ')}</dd></>)}
            {proposal.plates.length > 0 && (<><dt>Plates</dt><dd>{proposal.plates.join(', ')}</dd></>)}
            {proposal.time_window && (<><dt>Time</dt><dd>{proposal.time_window.start}–{proposal.time_window.end}</dd></>)}
            {proposal.min_dwell_seconds > 0 && (<><dt>Stays longer than</dt><dd>{proposal.min_dwell_seconds}s</dd></>)}
            <dt>Send to</dt><dd>{proposal.channels.join(', ')}</dd>
          </dl>
          <div className="row">
            <button className="btn" onClick={saveRule}>Create alert</button>
            <button className="btn ghost" onClick={() => setProposal(null)}>Cancel</button>
          </div>
        </div>
      )}

      {result && (
        <>
          <div className="chips">
            <span className="muted small">Understood ({f.source}):</span>
            {chips.length ? chips.map((c) => <span key={c} className="tag">{c}</span>) : <span className="muted small">no filters, showing latest</span>}
          </div>

          <h3>Objects seen ({result.sightings.length})</h3>
          <div className="sighting-grid">
            {result.sightings.map((s) => (
              <div key={s.id} className="sighting">
                {s.thumbnail_url ? <img src={mediaUrl(s.thumbnail_url)} alt="" loading="lazy" /> : <div className="noimg" />}
                <div className="small">
                  <strong>{s.label}</strong> {s.color && `· ${s.color}`} {s.plate && <span className="plate">{s.plate}</span>}
                  <div className="muted">{s.camera_id} · {formatTime(s.first_seen)}</div>
                  {s.zones.length > 0 && <div className="muted">zones: {s.zones.join(', ')}</div>}
                </div>
              </div>
            ))}
          </div>
          {result.sightings.length === 0 && <p className="muted">Nothing matched in the search index.</p>}

          <h3>Matching alerts ({result.events.length})</h3>
          <div className="event-grid">
            {result.events.map((e) => <EventCard key={e.id} event={e} />)}
          </div>
        </>
      )}
    </div>
  )
}
