// Backend base URL. Empty = same origin (dev proxy or backend serving the built app).
// For the future mobile/desktop apps set VITE_API_URL, e.g. https://cctv.example.com
export const API_BASE = import.meta.env.VITE_API_URL || ''

export const mediaUrl = (path) => (path ? `${API_BASE}${path}` : null)

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {}
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  cameras: () => request('/api/cameras'),
  restartCameras: () => request('/api/cameras/restart', { method: 'POST' }),
  setCameraEnabled: (id, enabled) => request(`/api/cameras/${encodeURIComponent(id)}/enabled?enabled=${enabled}`, { method: 'PATCH' }),
  streamUrl: (id) => `${API_BASE}/api/cameras/${id}/stream`,
  snapshotUrl: (id, raw = false) => `${API_BASE}/api/cameras/${encodeURIComponent(id)}/snapshot?raw=${raw}`,
  updateZones: (id, zones) => request(`/api/cameras/${encodeURIComponent(id)}/zones`, { method: 'PUT', body: JSON.stringify({ zones }) }),

  events: (params = {}) => request(`/api/events?${new URLSearchParams(params)}`),
  event: (id) => request(`/api/events/${id}`),
  ackEvent: (id) => request(`/api/events/${id}/ack`, { method: 'POST' }),
  ackAllEvents: () => request('/api/events/ack-all', { method: 'POST' }),
  stats: () => request('/api/events/stats'),

  rules: () => request('/api/rules'),
  createRule: (rule) => request('/api/rules', { method: 'POST', body: JSON.stringify(rule) }),
  updateRule: (id, rule) => request(`/api/rules/${id}`, { method: 'PUT', body: JSON.stringify(rule) }),
  setRuleEnabled: (id, enabled) => request(`/api/rules/${id}/enabled?enabled=${enabled}`, { method: 'PATCH' }),
  deleteRule: (id) => request(`/api/rules/${id}`, { method: 'DELETE' }),

  search: (prompt) => request('/api/search', { method: 'POST', body: JSON.stringify({ prompt }) }),
  proposeRule: (prompt) => request('/api/search/rule', { method: 'POST', body: JSON.stringify({ prompt }) }),
  ask: (event_id, question) => request('/api/search/ask', { method: 'POST', body: JSON.stringify({ event_id, question }) }),
  capabilities: () => request('/api/search/capabilities'),
}

export function wsUrl() {
  const base = API_BASE || window.location.origin
  return base.replace(/^http/, 'ws') + '/ws/events'
}

export function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
