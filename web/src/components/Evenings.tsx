import { Link } from 'react-router-dom'
import { dayKey, fmtCallTime, type TrendPoint } from '../api'
import { moodColor, moodWord } from '../mood'

const MIN_BAR = 18
const MAX_BAR = 128

/** Mood −0.5…+0.6 mapped to bar height; taller = brighter evening. */
export function barHeight(mood: number) {
  const t = Math.max(0, Math.min(1, (mood + 0.5) / 1.1))
  return MIN_BAR + t * (MAX_BAR - MIN_BAR)
}

type Slot = { key: string; date: Date; point?: TrendPoint; state: 'scored' | 'missed' | 'none' | 'tonight' }

function buildSlots(points: TrendPoint[], anchor: Date, days: number, tonight: boolean): Slot[] {
  const byDay = new Map<string, TrendPoint[]>()
  for (const p of points) {
    const k = dayKey(p.date)
    byDay.set(k, [...(byDay.get(k) ?? []), p])
  }
  const slots: Slot[] = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(anchor)
    d.setDate(d.getDate() - i)
    const k = dayKey(d)
    const list = byDay.get(k) ?? []
    const scored = list.filter((p) => p.mood !== null).at(-1)
    const missed = list.find((p) => p.status === 'missed' || p.status === 'failed')
    if (scored) slots.push({ key: k, date: d, point: scored, state: 'scored' })
    else if (missed) slots.push({ key: k, date: d, point: missed, state: 'missed' })
    else slots.push({ key: k, date: d, state: i === 0 && tonight ? 'tonight' : 'none' })
  }
  return slots
}

const weekday = (d: Date) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'narrow' }).format(d)
const dayNum = (d: Date) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric' }).format(d)
const longDay = (d: Date) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long' }).format(d)

export function Evenings({
  points, baseline, anchor, callTime, name, selectedId, days = 14, baselineLabel = 'Her usual', tonight = true,
}: {
  points: TrendPoint[]
  baseline: number | null
  anchor: Date
  callTime: string
  name: string
  selectedId?: number
  days?: number
  baselineLabel?: string
  tonight?: boolean
}) {
  const slots = buildSlots(points, anchor, days, tonight)
  const cols = { gridTemplateColumns: `repeat(${days}, 1fr)` }
  return (
    <div className="sky" role="group" aria-label={`${name}'s mood over the last ${days} evenings`}>
      <div className="sky-plot" style={cols}>
        {baseline !== null && (
          <div className="usual" style={{ bottom: barHeight(baseline) }} aria-hidden="true">
            <span>{baselineLabel}</span>
          </div>
        )}
        {slots.map((s, i) => {
          const isLast = i === slots.length - 1
          if (s.state === 'scored' && s.point) {
            const mood = s.point.mood as number
            const h = barHeight(mood)
            const color = moodColor(mood)
            const label = `${longDay(s.date)}: ${moodWord(mood)}${s.point.mismatch ? ', said she was fine but sounded low' : ''}${s.point.alerts.length ? ', alert sent' : ''}`
            return (
              <Link
                key={s.key}
                to={`/calls/${s.point.call_id}`}
                className={`eve${selectedId === s.point.call_id ? ' eve-selected' : ''}`}
                aria-label={label}
                title={label}
              >
                {s.point.mismatch && <i className="eve-ring" style={{ bottom: h + 7 }} aria-hidden="true" />}
                <span className={`eve-bar${mood >= 0.35 ? ' glow' : ''}`} style={{ height: h, background: color, color }} />
              </Link>
            )
          }
          if (s.state === 'missed' && s.point) {
            return (
              <Link key={s.key} to={`/calls/${s.point.call_id}`} className="eve eve-missed" aria-label={`${longDay(s.date)}: missed check-in`} title="Missed check-in">
                <span className="eve-bar" />
              </Link>
            )
          }
          if (s.state === 'tonight' && isLast) {
            return (
              <div key={s.key} className="eve eve-tonight" title={`Tonight's call at ${fmtCallTime(callTime)}`} aria-label={`Tonight's call at ${fmtCallTime(callTime)}`}>
                <span className="eve-bar" />
              </div>
            )
          }
          return (
            <div key={s.key} className="eve eve-none" aria-label={`${longDay(s.date)}: no call`}>
              <span className="eve-bar" />
            </div>
          )
        })}
      </div>
      <div className="sky-alerts" aria-hidden="true" style={cols}>
        {slots.map((s) => <span key={s.key} style={{ display: 'grid' }}>{s.point?.alerts.length ? <i /> : null}</span>)}
      </div>
      <div className="sky-days" aria-hidden="true" style={cols}>
        {slots.map((s, i) => (
          <div key={s.key} className={`sky-day${i === slots.length - 1 ? ' is-today' : ''}`}>
            {weekday(s.date)}
            <b>{dayNum(s.date)}</b>
          </div>
        ))}
      </div>
    </div>
  )
}

export function EveningsLegend({ baselineLabel = 'Her usual', alerts = true }: { baselineLabel?: string; alerts?: boolean }) {
  return (
    <div className="legend">
      <span><i className="scale" aria-hidden="true" /> Low to bright</span>
      <span><i className="dash" aria-hidden="true" /> {baselineLabel}</span>
      <span><i className="ring" aria-hidden="true" /> Said fine, sounded low</span>
      {alerts && <span><i className="dot" aria-hidden="true" /> Alert sent</span>}
    </div>
  )
}
