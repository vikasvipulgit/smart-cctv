import { useEffect, useState } from 'react'
import { api } from '../api'

function statusOf(c, pending) {
  if (pending) return { cls: '', text: pending === 'on' ? 'Turning on...' : 'Turning off...' }
  if (!c.enabled) return { cls: '', text: 'Off' }
  if (c.connected) return { cls: 'ok', text: 'Online' }
  return { cls: 'bad', text: c.error ? 'Offline' : 'Connecting...' }
}

const isWebcam = (c) => /^\d+$/.test(c.source || '')

export default function CamerasPage() {
  const [cameras, setCameras] = useState([])
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState({}) // camera id -> 'on' | 'off'
  const [error, setError] = useState(null)

  const load = () => api.cameras().then(setCameras).catch(() => {})
  useEffect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [])

  const restart = async () => {
    setBusy(true)
    try { await api.restartCameras() } finally { setBusy(false); load() }
  }

  const toggle = async (cam) => {
    const enabled = !cam.enabled
    setError(null)
    setPending((p) => ({ ...p, [cam.id]: enabled ? 'on' : 'off' }))
    try {
      const updated = await api.setCameraEnabled(cam.id, enabled)
      setCameras((cs) => cs.map((c) => (c.id === cam.id ? updated : c)))
    } catch (e) {
      setError(`${cam.name}: ${e.message.replace(/^\d+: /, '')}`)
    } finally {
      setPending((p) => {
        const { [cam.id]: _, ...rest } = p
        return rest
      })
    }
  }

  return (
    <div>
      <div className="toolbar">
        <h2>Cameras</h2>
        <button className="btn ghost" onClick={restart} disabled={busy}>{busy ? 'Restarting...' : 'Reload cameras.yaml'}</button>
      </div>

      {error && <div className="banner error">{error}</div>}

      <table className="table">
        <thead>
          <tr><th>On</th><th>Camera</th><th>Status</th><th>Source</th><th>FPS analysed</th><th>Zones</th><th>Last error</th><th></th></tr>
        </thead>
        <tbody>
          {cameras.map((c) => {
            const st = statusOf(c, pending[c.id])
            return (
              <tr key={c.id} className={c.enabled ? '' : 'cam-off'}>
                <td>
                  <label className="switch" title={c.enabled ? 'Turn camera off' : 'Turn camera on'}>
                    <input type="checkbox" checked={c.enabled} disabled={!!pending[c.id]}
                      aria-label={`${c.name} on/off`} onChange={() => toggle(c)} />
                    <span />
                  </label>
                </td>
                <td><strong>{c.name}</strong><div className="muted small">{c.id}</div></td>
                <td><span className={`dot ${st.cls}`} /> {st.text}</td>
                <td className="mono small">{c.source}</td>
                <td>{c.enabled ? c.processing_fps : '-'}</td>
                <td>{c.zones.map((z) => z.name).join(', ') || '-'}</td>
                <td className="small error-text">
                  {c.enabled && c.error}
                  {c.enabled && c.error && isWebcam(c) && (
                    <div className="muted">
                      macOS may be blocking the camera: System Settings → Privacy &amp; Security → Camera → allow
                      the app running <code>dev.sh</code> (VS Code or Terminal), then restart that app.
                    </div>
                  )}
                </td>
                <td><a className="btn small ghost" href={`#/cameras/${encodeURIComponent(c.id)}`}>Edit zones</a></td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <p className="muted small">
        Each camera that is on is read and analysed all the time. Turn off the ones you don't need. The choice is
        saved to <code>cameras.yaml</code>, and the webcam light goes off when its camera is off.
      </p>

      <div className="card help">
        <h3>Adding a camera</h3>
        <ol>
          <li>Find the camera's RTSP URL (see <code>docs/RTSP_GUIDE.md</code>, or run <code>python scripts/find_rtsp.py</code>).</li>
          <li>Check it plays in VLC: Media → Open Network Stream.</li>
          <li>Put the URL in <code>.env</code>, e.g. <code>GATE_RTSP_URL=rtsp://admin:password@192.168.1.64:554/...</code>, and restart <code>dev.sh</code>.</li>
          <li>Add the camera to <code>backend/config/cameras.yaml</code> with <code>source: "${'{'}GATE_RTSP_URL{'}'}"</code>. For the Mac's own camera use <code>source: "0"</code>.</li>
          <li>Click <strong>Reload cameras.yaml</strong> above, then turn the camera on with its switch.</li>
          <li>Click <strong>Edit zones</strong> to draw the areas to watch on the live picture.</li>
        </ol>
      </div>
    </div>
  )
}
