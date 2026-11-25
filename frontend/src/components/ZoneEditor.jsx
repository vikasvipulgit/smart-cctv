import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Draw and edit a camera's zones on a still frame, then save them to cameras.yaml.
// Zones are stored as normalised 0..1 (x, y) points, so they work at any stream resolution.

const COLORS = ['#4fd1c5', '#ecc94b', '#f687b3', '#90cdf4', '#f6ad55', '#9ae6b4', '#b794f4']
const SNAP_PX = 12 // clicking this close to the first point closes the polygon
const MAX_NAME = 40

const clamp01 = (v) => Math.min(1, Math.max(0, v))
const r4 = (v) => Math.round(clamp01(v) * 10000) / 10000

let keySeq = 0
const withKeys = (zones) =>
  zones.map((z) => ({ key: ++keySeq, name: z.name, origName: z.name, anchor: z.anchor || 'bottom', points: z.points.map((p) => [...p]) }))
const plain = (zones) => zones.map(({ name, points, anchor }) => ({ name: name.trim(), points, anchor: anchor || 'bottom' }))

// How a detected object counts as inside a zone (matches Zone.anchor in the backend)
const ANCHORS = [
  { value: 'bottom', label: 'Feet: bottom of the box is inside', hint: 'Best for CCTV looking at the ground' },
  { value: 'center', label: 'Centre of the box is inside', hint: 'Objects seen from the side or above' },
  { value: 'overlap', label: 'Box overlaps the zone (25%+)', hint: 'Best for webcams and close-ups, where people are cut off at the bottom' },
]

function nextName(zones) {
  const taken = new Set(zones.map((z) => z.name.trim().toLowerCase()))
  let i = zones.length + 1
  while (taken.has(`zone_${i}`)) i++
  return `zone_${i}`
}

function nameError(zone, zones) {
  const n = zone.name.trim()
  if (!n) return 'Name is required'
  if (n.length > MAX_NAME) return `Max ${MAX_NAME} characters`
  if (zones.some((z) => z !== zone && z.name.trim().toLowerCase() === n.toLowerCase())) return 'Name already used'
  return null
}

const isTyping = (el) => el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)

export default function ZoneEditor({ cameraId }) {
  const [camera, setCamera] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [zones, setZones] = useState([])
  const [baseline, setBaseline] = useState(null) // JSON of the saved zones
  const [selected, setSelected] = useState(null) // zone key
  const [drawing, setDrawing] = useState(null) // points of the polygon being drawn, or null
  const [hover, setHover] = useState(null) // cursor position (normalised) while drawing
  const [frameTick, setFrameTick] = useState(() => Date.now())
  const [frameOk, setFrameOk] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [rules, setRules] = useState([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null) // { type: 'error' | 'success', text }
  const [focusKey, setFocusKey] = useState(null)

  const history = useRef([]) // undo stack of zone arrays
  const drag = useRef(null)
  const renameStart = useRef(null) // zones when a name field got focus, for undo
  const svgRef = useRef(null)
  const boxRef = useRef(null)

  // ---------------------------------------------------------------- load
  useEffect(() => {
    let cancelled = false
    api.cameras()
      .then((cams) => {
        if (cancelled) return
        const cam = cams.find((c) => c.id === cameraId)
        if (!cam) return setLoadError(`Camera "${cameraId}" was not found in cameras.yaml.`)
        setCamera(cam)
        setZones(withKeys(cam.zones))
        setBaseline(JSON.stringify(plain(cam.zones)))
        setFrameOk(cam.connected)
      })
      .catch((e) => !cancelled && setLoadError(e.message))
    api.rules().then((r) => !cancelled && setRules(r)).catch(() => {})
    return () => { cancelled = true }
  }, [cameraId])

  // Keep the SVG overlay the same pixel size as the frame on screen.
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ w: width, h: height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [camera, frameOk])

  useEffect(() => {
    if (!autoRefresh) return
    const t = setInterval(() => setFrameTick(Date.now()), 1500)
    return () => clearInterval(t)
  }, [autoRefresh])

  const dirty = baseline !== null && JSON.stringify(plain(zones)) !== baseline
  const invalid = zones.some((z) => nameError(z, zones))

  useEffect(() => {
    if (!dirty) return
    const warn = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // ---------------------------------------------------------------- editing helpers
  const commit = (next) => {
    history.current.push(zones)
    if (history.current.length > 100) history.current.shift()
    setZones(next)
  }

  const undo = () => {
    if (drawing) {
      setDrawing(drawing.length > 1 ? drawing.slice(0, -1) : null)
      return
    }
    const prev = history.current.pop()
    if (prev) setZones(prev)
  }

  const updateZone = (key, patch) => setZones((zs) => zs.map((z) => (z.key === key ? { ...z, ...patch } : z)))

  const deleteZone = (key) => {
    commit(zones.filter((z) => z.key !== key))
    if (selected === key) setSelected(null)
  }

  const removeVertex = (key, index) => {
    const z = zones.find((zz) => zz.key === key)
    if (!z || z.points.length <= 3) {
      setMessage({ type: 'error', text: 'A zone needs at least 3 points. Delete the zone instead.' })
      return
    }
    commit(zones.map((zz) => (zz.key === key ? { ...zz, points: zz.points.filter((_, i) => i !== index) } : zz)))
  }

  const startDrawing = () => {
    setSelected(null)
    setMessage(null)
    setDrawing([])
  }

  const finishDrawing = () => {
    if (!drawing) return
    if (drawing.length < 3) {
      setMessage({ type: 'error', text: 'Add at least 3 points before finishing the zone.' })
      return
    }
    const zone = { key: ++keySeq, name: nextName(zones), origName: null, anchor: 'bottom', points: drawing }
    commit([...zones, zone])
    setSelected(zone.key)
    setFocusKey(zone.key)
    setDrawing(null)
    setHover(null)
    setMessage(null)
  }

  const cancelDrawing = () => {
    setDrawing(null)
    setHover(null)
  }

  const discard = () => {
    setZones(withKeys(JSON.parse(baseline)))
    history.current = []
    setSelected(null)
    setDrawing(null)
    setMessage(null)
  }

  const save = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const res = await api.updateZones(cameraId, plain(zones))
      setBaseline(JSON.stringify(res.zones))
      setZones((zs) => zs.map((z, i) => ({ ...z, name: res.zones[i]?.name ?? z.name, origName: res.zones[i]?.name ?? z.name })))
      setMessage({ type: 'success', text: 'Zones saved to cameras.yaml. Detection is using them now.' })
    } catch (e) {
      setMessage({ type: 'error', text: `Could not save: ${e.message}` })
    } finally {
      setSaving(false)
    }
  }

  // ---------------------------------------------------------------- keyboard
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !isTyping(e.target)) {
        e.preventDefault()
        undo()
        return
      }
      if (isTyping(e.target)) return
      if (e.key === 'Escape') {
        if (drawing) cancelDrawing()
        else setSelected(null)
      } else if (e.key === 'Enter' && drawing) {
        e.preventDefault()
        finishDrawing()
      } else if ((e.key === 'Backspace' || e.key === 'Delete') && drawing) {
        e.preventDefault()
        undo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // ---------------------------------------------------------------- pointer handling
  const toNorm = (e) => {
    const rect = svgRef.current.getBoundingClientRect()
    return [r4((e.clientX - rect.left) / rect.width), r4((e.clientY - rect.top) / rect.height)]
  }
  const px = ([x, y]) => [x * size.w, y * size.h]
  const distPx = (a, b) => Math.hypot((a[0] - b[0]) * size.w, (a[1] - b[1]) * size.h)

  const beginDrag = (e, info) => {
    e.stopPropagation()
    e.preventDefault()
    svgRef.current.setPointerCapture(e.pointerId)
    drag.current = { ...info, start: toNorm(e), before: zones, moved: info.moved || false }
  }

  const onVertexDown = (e, zone, index) => {
    if (drawing) return
    if (e.altKey || e.button === 2) {
      e.stopPropagation()
      removeVertex(zone.key, index)
      return
    }
    setSelected(zone.key)
    beginDrag(e, { kind: 'vertex', key: zone.key, index, orig: zone.points })
  }

  const onMidpointDown = (e, zone, index) => {
    if (drawing) return
    const p = toNorm(e)
    const points = [...zone.points.slice(0, index + 1), p, ...zone.points.slice(index + 1)]
    const next = zones.map((z) => (z.key === zone.key ? { ...z, points } : z))
    beginDrag(e, { kind: 'vertex', key: zone.key, index: index + 1, orig: points, moved: true })
    setZones(next)
  }

  const onPolygonDown = (e, zone) => {
    if (drawing) return
    setSelected(zone.key)
    beginDrag(e, { kind: 'move', key: zone.key, orig: zone.points })
  }

  const onBackgroundDown = (e) => {
    if (e.button !== 0) return
    if (!drawing) {
      setSelected(null)
      return
    }
    const p = toNorm(e)
    if (drawing.length >= 3 && distPx(p, drawing[0]) <= SNAP_PX) finishDrawing()
    else setDrawing([...drawing, p])
  }

  const onPointerMove = (e) => {
    const d = drag.current
    if (!d) {
      if (drawing) setHover(toNorm(e))
      return
    }
    const [x, y] = toNorm(e)
    let points
    if (d.kind === 'vertex') {
      points = d.orig.map((p, i) => (i === d.index ? [x, y] : p))
    } else {
      const xs = d.orig.map((p) => p[0])
      const ys = d.orig.map((p) => p[1])
      // keep the whole polygon inside the frame
      const dx = Math.min(1 - Math.max(...xs), Math.max(-Math.min(...xs), x - d.start[0]))
      const dy = Math.min(1 - Math.max(...ys), Math.max(-Math.min(...ys), y - d.start[1]))
      points = d.orig.map(([px0, py0]) => [r4(px0 + dx), r4(py0 + dy)])
    }
    d.moved = true
    setZones((zs) => zs.map((z) => (z.key === d.key ? { ...z, points } : z)))
  }

  const onPointerUp = () => {
    const d = drag.current
    drag.current = null
    if (d?.moved) {
      history.current.push(d.before)
      if (history.current.length > 100) history.current.shift()
    }
  }

  // ---------------------------------------------------------------- render
  if (loadError) {
    return (
      <div>
        <div className="toolbar"><h2>Edit zones</h2><a className="btn ghost" href="#/cameras">Back to cameras</a></div>
        <div className="banner error">{loadError}</div>
      </div>
    )
  }
  if (!camera) return <p className="muted">Loading camera...</p>

  const originalNames = new Set(JSON.parse(baseline || '[]').map((z) => z.name))
  const currentNames = new Set(zones.map((z) => z.name.trim()))
  const ruleWarnings = rules.filter(
    (r) => r.zone && !currentNames.has(r.zone) &&
      ((r.cameras || []).includes(cameraId) || (!(r.cameras || []).length && originalNames.has(r.zone))),
  )

  const colorOf = (zone) => COLORS[zones.indexOf(zone) % COLORS.length]
  const sel = zones.find((z) => z.key === selected)
  const snapping = drawing && hover && drawing.length >= 3 && distPx(hover, drawing[0]) <= SNAP_PX
  const svgClass = `zone-svg${drawing ? ' drawing' : ''}`

  const leave = (e) => {
    if (dirty && !window.confirm('You have unsaved zone changes. Leave without saving?')) e.preventDefault()
  }

  return (
    <div>
      <div className="toolbar">
        <h2>Zones · {camera.name} <span className="muted small">{camera.id}</span></h2>
        <a className="btn ghost" href="#/cameras" onClick={leave}>Back to cameras</a>
      </div>

      <div className="zone-layout">
        <div className="zone-canvas">
          <div className="zone-stage">
            {frameOk ? (
              <img
                ref={boxRef}
                className="zone-frame"
                src={`${api.snapshotUrl(cameraId, true)}&t=${frameTick}`}
                alt={`Current frame from ${camera.name}`}
                draggable={false}
                onError={() => setFrameOk(false)}
              />
            ) : (
              <div ref={boxRef} className="zone-frame placeholder">
                <span>No live frame (camera offline or disabled). You can still edit the zones; the shape is shown on a 16:9 canvas.</span>
              </div>
            )}
            {size.w > 0 && (
              <svg
                ref={svgRef}
                className={svgClass}
                width={size.w}
                height={size.h}
                viewBox={`0 0 ${size.w} ${size.h}`}
                onPointerDown={onBackgroundDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                onPointerLeave={() => setHover(null)}
                onContextMenu={(e) => e.preventDefault()}
              >
                {zones.map((z) => {
                  const color = colorOf(z)
                  const pts = z.points.map(px)
                  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length
                  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length
                  const isSel = z.key === selected
                  return (
                    <g key={z.key} className={isSel ? 'zone selected' : 'zone'}>
                      <polygon
                        points={pts.map((p) => p.join(',')).join(' ')}
                        fill={color}
                        fillOpacity={isSel ? 0.28 : 0.16}
                        stroke={color}
                        strokeWidth={isSel ? 2.5 : 2}
                        style={{ pointerEvents: drawing ? 'none' : 'auto', cursor: isSel ? 'move' : 'pointer' }}
                        onPointerDown={(e) => onPolygonDown(e, z)}
                      />
                      <text x={cx} y={cy} className="zone-label" fill={color}>{z.name || '(unnamed)'}</text>
                    </g>
                  )
                })}

                {sel && !drawing && (
                  <g>
                    {sel.points.map((p, i) => {
                      const [ax, ay] = px(p)
                      const [bx, by] = px(sel.points[(i + 1) % sel.points.length])
                      return (
                        <g key={`m${i}`} className="midpoint" onPointerDown={(e) => onMidpointDown(e, sel, i)}>
                          <circle cx={(ax + bx) / 2} cy={(ay + by) / 2} r={12} fill="transparent" />
                          <circle cx={(ax + bx) / 2} cy={(ay + by) / 2} r={4} fill="#0f1216" stroke={colorOf(sel)} strokeWidth={1.5} />
                        </g>
                      )
                    })}
                    {sel.points.map((p, i) => {
                      const [x, y] = px(p)
                      return (
                        <g key={`v${i}`} className="vertex"
                          onPointerDown={(e) => onVertexDown(e, sel, i)}
                          onDoubleClick={(e) => { e.stopPropagation(); removeVertex(sel.key, i) }}>
                          <circle cx={x} cy={y} r={14} fill="transparent" />
                          <circle cx={x} cy={y} r={6} fill={colorOf(sel)} stroke="#0f1216" strokeWidth={2} />
                        </g>
                      )
                    })}
                  </g>
                )}

                {drawing && (
                  <g className="draft" style={{ pointerEvents: 'none' }}>
                    {drawing.length > 1 && (
                      <polyline points={drawing.map(px).map((p) => p.join(',')).join(' ')} fill="none" stroke="#fff" strokeWidth={2} />
                    )}
                    {hover && drawing.length > 0 && (
                      <line x1={px(drawing.at(-1))[0]} y1={px(drawing.at(-1))[1]}
                        x2={px(snapping ? drawing[0] : hover)[0]} y2={px(snapping ? drawing[0] : hover)[1]}
                        stroke="#fff" strokeWidth={1.5} strokeDasharray="5 4" />
                    )}
                    {drawing.map((p, i) => {
                      const [x, y] = px(p)
                      return <circle key={i} cx={x} cy={y} r={i === 0 && snapping ? 9 : 5}
                        fill={i === 0 ? '#4fd1c5' : '#fff'} stroke="#0f1216" strokeWidth={2} />
                    })}
                  </g>
                )}
              </svg>
            )}
          </div>

          <div className="zone-frame-tools">
            <button className="btn small ghost" onClick={() => { setFrameOk(true); setFrameTick(Date.now()) }}>Refresh frame</button>
            <label className="check small">
              <input type="checkbox" checked={autoRefresh} onChange={(e) => { setFrameOk(true); setAutoRefresh(e.target.checked) }} />
              Auto-refresh
            </label>
            {drawing && (
              <span className="muted small">
                {drawing.length === 0 ? 'Click on the image to place the first point.' :
                  drawing.length < 3 ? `Point ${drawing.length} placed. Keep clicking.` :
                    'Click the first point (or press Enter) to close the zone.'}
              </span>
            )}
          </div>
        </div>

        <aside className="zone-panel">
          <div className="zone-actions">
            {drawing ? (
              <>
                <button className="btn" onClick={finishDrawing} disabled={drawing.length < 3}>Finish zone</button>
                <button className="btn ghost" onClick={undo} disabled={!drawing.length}>Undo point</button>
                <button className="btn ghost" onClick={cancelDrawing}>Cancel</button>
              </>
            ) : (
              <button className="btn" onClick={startDrawing}>+ Draw zone</button>
            )}
          </div>

          {zones.length === 0 && !drawing && (
            <p className="muted small">No zones yet. Without a zone, rules look at the whole frame.</p>
          )}

          <ul className="zone-list">
            {zones.map((z) => {
              const err = nameError(z, zones)
              const renamed = z.origName && z.origName !== z.name.trim()
              return (
                <li key={z.key} className={z.key === selected ? 'active' : ''} style={{ '--zone': colorOf(z) }}
                  onClick={() => !drawing && setSelected(z.key)}>
                  <span className="swatch" />
                  <div className="zone-item-body">
                    <input
                      value={z.name}
                      maxLength={MAX_NAME + 10}
                      aria-label="Zone name"
                      autoFocus={focusKey === z.key}
                      onFocus={(e) => {
                        if (focusKey === z.key) { e.target.select(); setFocusKey(null) }
                        renameStart.current = zones
                      }}
                      onBlur={() => {
                        const before = renameStart.current
                        renameStart.current = null
                        if (before && JSON.stringify(plain(before)) !== JSON.stringify(plain(zones))) history.current.push(before)
                      }}
                      onChange={(e) => updateZone(z.key, { name: e.target.value })}
                    />
                    <div className="small muted">
                      {z.points.length} points{renamed && <> · was <code>{z.origName}</code></>}
                    </div>
                    <label className="small muted zone-anchor">
                      Counts as inside when
                      <select value={z.anchor} title={ANCHORS.find((a) => a.value === z.anchor)?.hint}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => commit(zones.map((zz) => (zz.key === z.key ? { ...zz, anchor: e.target.value } : zz)))}>
                        {ANCHORS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                      </select>
                    </label>
                    {err && <div className="small error-text">{err}</div>}
                  </div>
                  <button className="btn small danger" title="Delete zone"
                    onClick={(e) => { e.stopPropagation(); deleteZone(z.key) }}>Delete</button>
                </li>
              )
            })}
          </ul>

          {ruleWarnings.length > 0 && (
            <div className="banner warn small">
              {ruleWarnings.map((r) => (
                <div key={r.id}>Rule <strong>{r.name}</strong> uses zone <code>{r.zone}</code>, which this camera will no longer have. Keep the old name or edit the rule.</div>
              ))}
            </div>
          )}

          {message && <div className={`banner ${message.type} small`}>{message.text}</div>}

          <div className="zone-actions">
            <button className="btn" onClick={save} disabled={!dirty || invalid || saving || !!drawing}>
              {saving ? 'Saving...' : 'Save zones'}
            </button>
            <button className="btn ghost" onClick={undo} disabled={!!drawing || history.current.length === 0}>Undo</button>
            <button className="btn ghost" onClick={discard} disabled={!dirty}>Discard</button>
          </div>
          {dirty && <p className="small muted">Unsaved changes.</p>}

          <div className="card help small">
            <strong>How it works</strong>
            <ul>
              <li><strong>Draw:</strong> click points around the area, then click the first point or press Enter. Esc cancels.</li>
              <li><strong>Edit:</strong> select a zone, drag its corners or drag the shape to move it. Drag a small midpoint dot to add a corner.</li>
              <li><strong>Remove a corner:</strong> double-click it (or Alt-click).</li>
              <li><strong>Undo:</strong> ⌘Z / Ctrl+Z.</li>
              <li><strong>Counts as inside when:</strong> <em>Feet</em> (default) suits CCTV looking at the ground, so draw those zones on the floor. For a webcam or close-up, where people are cut off at the bottom, use <em>Box overlaps the zone</em>.</li>
              <li>Rules refer to zones by name. Renaming a zone means updating rules that use it.</li>
            </ul>
          </div>
        </aside>
      </div>
    </div>
  )
}
