import { formatTime, mediaUrl } from '../api'

export default function EventCard({ event, compact = false }) {
  return (
    <a className={`event-card ${event.acknowledged ? 'acked' : ''} ${compact ? 'compact' : ''}`} href={`#/events/${event.id}`}>
      {event.snapshot_url ? <img src={mediaUrl(event.snapshot_url)} alt="" loading="lazy" /> : <div className="noimg" />}
      <div className="event-body">
        <div className="event-title">{event.rule_name}</div>
        {event.message && <div className="event-message small">{event.message}</div>}
        <div className="tags">
          <span className="tag">{event.camera_id}</span>
          <span className="tag">{event.label}</span>
          {event.color && <span className="tag">{event.color}</span>}
          {event.plate && <span className="tag plate">{event.plate}</span>}
          {event.text && <span className="tag plate">{event.text}</span>}
          {event.zone && <span className="tag">{event.zone}</span>}
        </div>
        <div className="muted small">{formatTime(event.created_at)}</div>
      </div>
    </a>
  )
}
