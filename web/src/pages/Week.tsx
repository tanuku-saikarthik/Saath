import { Link } from 'react-router-dom'
import { useApi, type TrendPoint, type Week as WeekData } from '../api'
import { useParent } from '../App'
import { Evenings, EveningsLegend } from '../components/Evenings'
import { IconArrow } from '../components/Icons'
import { ErrorNote, Loading } from '../components/Pieces'
import { EMOTION_WORDS, moodColor } from '../mood'

const range = (from: string, to: string) => {
  const f = new Date(`${from}T12:00:00+05:30`)
  const t = new Date(`${to}T12:00:00+05:30`)
  const day = (d: Date, month: boolean) =>
    new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', ...(month ? { month: 'short' } : {}) }).format(d)
  const sameMonth = f.getMonth() === t.getMonth()
  return `${day(f, !sameMonth)} to ${day(t, true)}`
}

const shortDay = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'long' }).format(new Date(`${iso}T12:00:00+05:30`))

function medLine(m: WeekData['medicines'][number]) {
  if (!m.asked) return 'Not asked about this week'
  const parts = [`Taken ${m.taken} of ${m.asked} times it came up`]
  if (m.missed) parts.push(`missed ${m.missed}`)
  if (m.unclear) parts.push(`not sure ${m.unclear}`)
  return parts.join(', ')
}

export default function Week() {
  const { parent } = useParent()
  const { data: w, error, loading } = useApi<WeekData>(`/api/parents/${parent.id}/week`)
  if (loading && !w) return <Loading />
  if (error) return <ErrorNote message={error} />
  if (!w) return null
  const name = parent.address_term
  const points: TrendPoint[] = w.evenings
    .filter((e) => e.call_id !== null)
    .map((e) => ({
      call_id: e.call_id!, date: `${e.date}T19:00:00+05:30`, status: e.status === 'completed' ? 'completed' : 'missed',
      is_seeded: false, mood: e.mood, text_valence: null, voice_valence: null, mismatch: e.mismatch, alerts: [],
    }))
  const anchor = new Date(`${w.to}T20:00:00+05:30`)
  const skipped = Object.entries(w.meals_skipped).filter(([, n]) => n > 0)
  const alertTotal = Object.values(w.alerts).reduce((a, b) => a + (b ?? 0), 0)
  const cut = w.sentence.indexOf('. ')
  const headline = cut === -1 ? w.sentence : w.sentence.slice(0, cut + 1)
  const detail = cut === -1 ? '' : w.sentence.slice(cut + 2)

  return (
    <div className="week">
      <p className="meta">{name}'s week, {range(w.from, w.to)}</p>
      <h1 className="answer" style={{ maxWidth: '24ch' }}>{headline}</h1>
      {detail && <p className="week-detail">{detail}</p>}

      <section className="section" aria-labelledby="wk-strip">
        <h2 className="h2" id="wk-strip">Seven evenings</h2>
        <Evenings points={points} baseline={w.mood_prev} anchor={anchor} callTime={parent.call_time} name={name} days={7} baselineLabel="Last week" tonight={false} />
        <EveningsLegend baselineLabel="Last week" alerts={false} />
      </section>

      <div className="week-grid">
        <section aria-labelledby="wk-basics">
          <h2 className="h2" id="wk-basics">The basics</h2>
          <div className="basics">
            <div className="basic">
              <div className="basic-label">Check-ins</div>
              <div>Saath reached her on {w.reached} of 7 evenings{w.missed ? `, ${w.missed} missed` : ''}.</div>
            </div>
            {w.medicines.map((m) => {
              const r = w.reminders?.find((x) => x.name === m.name)
              return (
                <div className="basic" key={m.name}>
                  <div className="basic-label">{m.name}</div>
                  <div>
                    {medLine(m)}
                    {r && <p className="meta small" style={{ margin: '4px 0 0' }}>Reminder calls: she answered {r.answered} of {r.placed} and took it {r.taken === r.answered ? 'every time' : `on ${r.taken}`}.</p>}
                  </div>
                </div>
              )
            })}
            <div className="basic">
              <div className="basic-label">Meals</div>
              <div>{skipped.length ? skipped.map(([k, n]) => `skipped ${k} ${n === 1 ? 'once' : `${n} times`}`).join(', ').replace(/^./, (c) => c.toUpperCase()) : 'No skipped meals mentioned.'}</div>
            </div>
            {(w.called_saath ?? 0) > 0 && (
              <div className="basic">
                <div className="basic-label">She called</div>
                <div>{name} called Saath herself {w.called_saath === 1 ? 'once' : `${w.called_saath} times`}.</div>
              </div>
            )}
            {(w.voice_changes?.length ?? 0) > 0 && (
              <div className="basic">
                <div className="basic-label">Her voice</div>
                <div>Lately she has been {w.voice_changes!.length > 1 ? `${w.voice_changes!.slice(0, -1).join(', ')} and ${w.voice_changes!.at(-1)}` : w.voice_changes![0]}, compared with her usual. A reason to call, not a diagnosis.</div>
              </div>
            )}
            {w.said_fine_sounded_low > 0 && (
              <div className="basic">
                <div className="basic-label">Said fine</div>
                <div>On {w.said_fine_sounded_low} {w.said_fine_sounded_low === 1 ? 'call' : 'calls'} she said she was fine but sounded low.</div>
              </div>
            )}
          </div>
        </section>

        <section aria-labelledby="wk-feel">
          <h2 className="h2" id="wk-feel">What she felt most</h2>
          {w.top_feelings.length ? (
            <div className="bars">
              {w.top_feelings.map((e) => (
                <div className="bar-row" key={e.label}>
                  <span>{EMOTION_WORDS[e.label] ?? e.label}</span>
                  <span className="bar"><i style={{ width: `${Math.min(1, e.score) * 100}%` }} /></span>
                  <span className="bar-val">{Math.round(e.score * 100)}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted">No calls to read from this week.</p>}
          {w.topics.length > 0 && (
            <>
              <h3 className="h3" style={{ marginTop: 22 }}>What she talked about</h3>
              <div className="chips">{w.topics.map((t) => <span className="chip" key={t}>{t}</span>)}</div>
            </>
          )}
        </section>
      </div>

      {(w.brightest || w.lowest) && (
        <section className="section" aria-labelledby="wk-moments">
          <h2 className="h2" id="wk-moments">Moments</h2>
          <div className="list">
            {[['Brightest evening', w.brightest], ['Hardest evening', w.lowest]].map(([label, m]) =>
              m && typeof m === 'object' ? (
                <Link key={label as string} to={`/calls/${m.call_id}`} className="row">
                  <span className="row-sw" style={{ background: moodColor(m.mood) }} aria-hidden="true" />
                  <div>
                    <p className="row-title">{m.headline}</p>
                    <p className="row-meta">{label as string}, {shortDay(m.date)}</p>
                  </div>
                  <IconArrow style={{ width: 18, height: 18, color: 'var(--ink-3)' }} />
                </Link>
              ) : null,
            )}
          </div>
        </section>
      )}

      {w.messages.length > 0 && (
        <section className="section" aria-labelledby="wk-msg">
          <h2 className="h2" id="wk-msg">Your messages</h2>
          <div className="msg" style={{ gap: 14 }}>
            {w.messages.map((m, i) => (
              <div className="msg-thread" key={i}>
                <p className="msg-you"><span className="msg-who">You, {shortDay(m.delivered)}</span>{m.text}</p>
                {m.reply && <p className="msg-her"><span className="msg-who">{name} replied</span>{m.reply}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      <p className="muted small" style={{ marginTop: 28 }}>
        {alertTotal ? (
          <>Saath sent {alertTotal} {alertTotal === 1 ? 'alert' : 'alerts'} this week. <Link to="/alerts">See alerts</Link></>
        ) : 'No alerts this week.'}
      </p>
    </div>
  )
}

