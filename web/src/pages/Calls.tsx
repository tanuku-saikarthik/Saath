import { Link } from 'react-router-dom'
import { anchorDate, fmtDay, fmtDuration, fmtTime, useApi, type Call } from '../api'
import { useParent } from '../App'
import { ErrorNote, Loading } from '../components/Pieces'
import { moodColor } from '../mood'

const KIND_PILL: Partial<Record<Call['kind'], string>> = {
  reminder: 'Medicine reminder', inbound: 'She called Saath', callback: 'Saath called her back',
}

function title(c: Call, name: string) {
  if (c.headline) return c.headline
  if (c.kind === 'reminder') return c.status === 'missed' ? `No answer to the ${c.reminder_for || 'medicine'} reminder` : c.status === 'failed' ? "Reminder couldn't be placed" : `${c.reminder_for || 'Medicine'} reminder`
  if (c.kind === 'inbound' && c.status === 'missed') return `${name} called, but the line dropped before she spoke`
  if (c.kind === 'callback' && c.status === 'missed') return "She didn't answer Saath's call back"
  if (c.kind === 'intro') return c.status === 'failed' ? 'Intro call could not be placed' : `Intro call with ${name}`
  if (c.status === 'missed') return c.kind === 'retry' ? 'Second try also unanswered' : 'No answer'
  if (c.status === 'failed') return "Call couldn't be placed"
  if (c.status === 'processing') return 'Listening back to the call'
  return 'Calling now'
}

export default function Calls() {
  const { parent } = useParent()
  const { data, error, loading } = useApi<Call[]>(`/api/parents/${parent.id}/calls?limit=30`)
  if (loading && !data) return <Loading />
  if (error) return <ErrorNote message={error} />
  const calls = data ?? []
  const anchor = anchorDate()

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Calls with {parent.address_term}</h1>
      </div>
      {calls.length === 0 ? (
        <p className="empty">No calls yet. The first one goes out tonight.</p>
      ) : (
        <div className="list">
          {calls.map((c) => {
            const scored = c.mood_score !== null && c.kind !== 'reminder'
            return (
              <Link key={c.id} to={`/calls/${c.id}`} className="row">
                <span className={`row-sw${scored ? '' : ' hollow'}`} style={scored ? { background: moodColor(c.mood_score) } : undefined} aria-hidden="true" />
                <div>
                  <p className="row-title">{title(c, parent.address_term)}</p>
                  <p className="row-meta">
                    {fmtDay(c.scheduled_at, anchor)}, {fmtTime(c.scheduled_at)}
                    {c.duration_s ? `, ${fmtDuration(c.duration_s)}` : ''}
                  </p>
                </div>
                <div className="row-side">
                  {KIND_PILL[c.kind] && <span className="pill">{KIND_PILL[c.kind]}</span>}
                  {c.mismatch && <span className="pill">Said fine, sounded low</span>}
                  {c.is_seeded && <span className="pill seeded">Sample</span>}
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </>
  )
}
