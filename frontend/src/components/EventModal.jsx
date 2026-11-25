import { useEffect, useState } from 'react'
import { api, formatTime, mediaUrl } from '../api'

export default function EventModal({ eventId, onClose }) {
  const [event, setEvent] = useState(null)
  const [error, setError] = useState(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(false)

  useEffect(() => {
    api.event(eventId).then(setEvent).catch((e) => setError(e.message))
  }, [eventId])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const ack = async () => setEvent(await api.ackEvent(eventId))

  const ask = async (e) => {
    e.preventDefault()
    if (!question.trim()) return
    setAsking(true)
    setAnswer(null)
    try {
      const res = await api.ask(eventId, question)
      setAnswer({ ok: true, text: res.answer })
    } catch (err) {
      setAnswer({ ok: false, text: err.message })
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        {error && <p className="error">{error}</p>}
        {event && (
          <>
            <h2>{event.rule_name}</h2>
            <p className="muted">{formatTime(event.created_at)} · {event.camera_id}</p>
            {event.snapshot_url && <img className="snapshot" src={mediaUrl(event.snapshot_url)} alt="Event snapshot" />}
            {event.message && <p className="event-message">{event.message}</p>}
            <dl className="details">
              <dt>Object</dt><dd>{event.label} ({Math.round(event.confidence * 100)}%)</dd>
              {event.color && (<><dt>Colour</dt><dd>{event.color}</dd></>)}
              {event.plate && (<><dt>Plate</dt><dd className="plate">{event.plate}</dd></>)}
              {event.text && (<><dt>Text read</dt><dd className="plate">{event.text}</dd></>)}
              {event.zone && (<><dt>Zone</dt><dd>{event.zone}</dd></>)}
              {event.track_id != null && (<><dt>Track</dt><dd>#{event.track_id}</dd></>)}
            </dl>
            <div className="row">
              {event.acknowledged ? <span className="tag ok">Acknowledged</span> : <button className="btn" onClick={ack}>Acknowledge</button>}
            </div>

            <form className="ask" onSubmit={ask}>
              <label>Ask AI about this snapshot</label>
              <div className="row">
                <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Is the person carrying anything?" />
                <button className="btn" disabled={asking}>{asking ? 'Asking...' : 'Ask'}</button>
              </div>
              {answer && <p className={answer.ok ? 'answer' : 'error'}>{answer.text}</p>}
            </form>
          </>
        )}
      </div>
    </div>
  )
}
