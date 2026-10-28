import { useState } from 'react'
import { api, DemoActionError, fmtDay, fmtTime, type Alert, type Analysis, type Parent } from '../api'
import { IconCheck, IconCross, IconPhone, IconQuestion } from './Icons'

const MEAL_NAMES: Record<string, string> = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner' }

function Tick({ state, children }: { state: string; children: React.ReactNode }) {
  const ok = state === 'eaten' || state === 'taken'
  const bad = state === 'skipped' || state === 'missed'
  const unclear = state === 'unclear'
  const cls = ok ? 'ok' : bad || unclear ? 'warn' : 'off'
  const word = ok ? '' : bad ? (state === 'missed' ? 'missed' : 'skipped') : unclear ? 'not sure' : 'not asked'
  return (
    <span className={`tick ${cls}`}>
      {ok ? <IconCheck /> : bad ? <IconCross /> : <IconQuestion />}
      {children}
      {word && <span className="muted">({word})</span>}
    </span>
  )
}

export function Basics({ a }: { a: Analysis }) {
  return (
    <div className="basics">
      <div className="basic">
        <div className="basic-label">Meals</div>
        <div>
          <div className="ticks">
            {(['breakfast', 'lunch', 'dinner'] as const).map((k) => (
              <Tick key={k} state={a.meals?.[k] ?? 'not_discussed'}>{MEAL_NAMES[k]}</Tick>
            ))}
          </div>
          {a.meals?.note && <p className="meta small" style={{ marginTop: 6 }}>{a.meals.note}</p>}
        </div>
      </div>
      <div className="basic">
        <div className="basic-label">Medicines</div>
        <div className="ticks">
          {a.meds.length ? a.meds.map((m) => <Tick key={m.name} state={m.status}>{m.name}</Tick>) : <span className="muted">None listed</span>}
        </div>
      </div>
      {(a.topics.length > 0 || a.health_mentions.length > 0) && (
        <div className="basic">
          <div className="basic-label">She talked about</div>
          <div className="chips">
            {[...a.topics, ...a.health_mentions.filter((h) => !a.topics.includes(h))].map((t) => <span className="chip" key={t}>{t}</span>)}
          </div>
        </div>
      )}
    </div>
  )
}

export function AlertCard({ alert, parent, onSeen, anchor }: { alert: Alert; parent: Parent; onSeen?: () => void; anchor?: Date }) {
  const [msg, setMsg] = useState('')
  const markSeen = async () => {
    try {
      await api(`/api/alerts/${alert.id}/seen`, { method: 'POST' })
      onSeen?.()
    } catch (e) {
      setMsg(e instanceof DemoActionError ? e.message : (e as Error).message)
    }
  }
  return (
    <article className={`alert ${alert.kind}`} aria-label={alert.title}>
      <p className="alert-when">{fmtDay(alert.created_at, anchor)}, {fmtTime(alert.created_at)}</p>
      <h3 className="alert-title">{alert.title}</h3>
      <p className="alert-reason">{alert.reason}</p>
      {alert.talking_points.length > 0 && (
        <div className="talk">
          <p>{alert.kind === 'urgent' || alert.kind === 'missed' || alert.kind === 'sos' ? 'What to do' : 'Things to talk about when you call'}</p>
          <ul>{alert.talking_points.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
      <div className="alert-actions">
        <a className="btn btn-primary btn-sm" href={`tel:${parent.phone}`}><IconPhone /> Call {parent.address_term}</a>
        <span className="meta small" style={{ userSelect: 'all' }}>{parent.phone}</span>
        {!alert.seen && onSeen && <button className="btn btn-text btn-sm" onClick={markSeen}>Mark as read</button>}
        {alert.seen && <span className="meta small">Read</span>}
      </div>
      {alert.notified && <p className="delivery"><IconCheck /> {alert.notified}</p>}
      {alert.notify_error && <p className="delivery failed"><IconCross /> {alert.notify_error}</p>}
      {msg && <p className="toast">{msg}</p>}
    </article>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <p className="loading" role="status">{what}…</p>
}

export function ErrorNote({ message }: { message: string }) {
  return <p className="empty" role="alert">{message}</p>
}
