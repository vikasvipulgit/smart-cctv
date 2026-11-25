import { useEffect, useState } from 'react'
import { api } from '../api'

const EMPTY_RULE = {
  id: '',
  name: '',
  enabled: true,
  cameras: [],
  classes: ['person'],
  zone: null,
  colors: [],
  plates: [],
  min_dwell_seconds: 0,
  time_window: null,
  cooldown_seconds: 60,
  min_confidence: 0,
  channels: ['websocket'],
  text_pattern: null,
  per_camera: false,
  message: null,
}

function describe(rule) {
  const parts = [rule.text_pattern ? `reads text matching /${rule.text_pattern}/`
    : rule.classes.length ? rule.classes.join('/') : 'any object']
  if (rule.colors.length) parts.unshift(rule.colors.join('/'))
  if (rule.zone) parts.push(`in ${rule.zone}`)
  if (rule.plates.length) parts.push(`plate ${rule.plates.join(', ')}`)
  if (rule.time_window) parts.push(`${rule.time_window.start}–${rule.time_window.end}`)
  if (rule.min_dwell_seconds) parts.push(`stays > ${rule.min_dwell_seconds}s`)
  if (rule.cameras.length) parts.push(`on ${rule.cameras.join(', ')}`)
  if (rule.per_camera) parts.push('once per arrival')
  if (rule.message) parts.push(`says “${rule.message}”`)
  return parts.join(' · ')
}

export default function RulesPage() {
  const [rules, setRules] = useState([])
  const [editing, setEditing] = useState(null) // { original id | null, text }
  const [error, setError] = useState(null)

  const load = () => api.rules().then(setRules).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const toggle = async (r) => { await api.setRuleEnabled(r.id, !r.enabled); load() }
  const remove = async (r) => {
    if (!window.confirm(`Delete rule "${r.name}"?`)) return
    await api.deleteRule(r.id)
    load()
  }

  const save = async () => {
    setError(null)
    try {
      const rule = JSON.parse(editing.text)
      if (editing.originalId) await api.updateRule(editing.originalId, rule)
      else await api.createRule(rule)
      setEditing(null)
      load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div>
      <div className="toolbar">
        <h2>Rules</h2>
        <button className="btn" onClick={() => setEditing({ originalId: null, text: JSON.stringify(EMPTY_RULE, null, 2) })}>New rule</button>
        <a className="btn ghost" href="#/search">Create from a prompt</a>
      </div>
      {error && <div className="banner error">{error}</div>}

      <div className="rule-list">
        {rules.map((r) => (
          <div key={r.id} className={`rule ${r.enabled ? '' : 'disabled'}`}>
            <label className="switch">
              <input type="checkbox" checked={r.enabled} onChange={() => toggle(r)} />
              <span />
            </label>
            <div className="rule-body">
              <strong>{r.name}</strong>
              <div className="muted small">{describe(r)}</div>
              <div className="tags">{r.channels.map((c) => <span key={c} className="tag">{c}</span>)}<span className="tag">cooldown {r.cooldown_seconds}s</span></div>
            </div>
            <button className="btn small ghost" onClick={() => setEditing({ originalId: r.id, text: JSON.stringify(r, null, 2) })}>Edit</button>
            <button className="btn small danger" onClick={() => remove(r)}>Delete</button>
          </div>
        ))}
      </div>

      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editing.originalId ? 'Edit rule' : 'New rule'}</h2>
            <p className="muted small">
              classes: YOLO labels (person, car, truck, bus, motorcycle...). zone: a zone name from cameras.yaml.
              channels: websocket, telegram, email, sms, push. time_window: {'{"start": "22:00", "end": "06:00"}'}.
              text_pattern: read numbers/text in the picture, e.g. {'"\\\\d{2,}"'} for any number with 2+ digits (ignores classes).
              per_camera: true = one alert per arrival instead of per tracked object. message: alert text, e.g.
              {' "Number seen: {text}"'}; placeholders {'{text} {label} {camera} {zone} {plate} {rule}'}.
            </p>
            <textarea rows={22} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} spellCheck={false} />
            <div className="row">
              <button className="btn" onClick={save}>Save</button>
              <button className="btn ghost" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
