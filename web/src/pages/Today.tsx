import { useState } from 'react'
import { Link } from 'react-router-dom'
import { anchorDate, api, DemoActionError, fmtCallTime, fmtDay, fmtDuration, fmtTime, useApi, type Call, type Overview, type Trend } from '../api'
import { useParent } from '../App'
import { Evenings, EveningsLegend } from '../components/Evenings'
import { IconArrow, IconPhone, IconVoice } from '../components/Icons'
import { MessageCard } from '../components/MessageCard'
import { AlertCard, Basics, ErrorNote, Loading } from '../components/Pieces'
import { moodColor, moodWord } from '../mood'

function trailingMismatches(trend: Trend) {
  let n = 0
  for (const p of [...trend.points].reverse()) {
    if (p.mood === null) continue
    if (!p.mismatch) break
    n++
  }
  return n
}

function compareToUsual(o: Overview) {
  const s = o.stats
  if (!s.enough || s.delta === null) return ''
  if (s.delta <= -0.15) return 'Lower than her usual for the last 3 calls'
  if (s.delta >= 0.15) return 'Brighter than her usual lately'
  return 'Close to her usual'
}

function LatestNotScored({ call, name }: { call: Call; name: string }) {
  const text: Record<string, string> = {
    queued: `Saath is calling ${name} now.`,
    in_progress: `Saath is on the phone with ${name}.`,
    processing: `The call just ended. Saath is listening back to it.`,
    missed: `${name} didn't pick up${call.kind === 'retry' ? ' the retry either' : ''}.`,
    failed: `The call couldn't be placed: ${call.error || 'unknown error'}.`,
  }
  return <p className="meta" style={{ marginTop: 8 }}>{text[call.status] ?? ''}</p>
}

export default function Today() {
  const { parent, setUnseen } = useParent()
  const ov = useApi<Overview>(`/api/parents/${parent.id}/overview`)
  const tr = useApi<Trend>(`/api/parents/${parent.id}/trend?days=14`)
  const [callMsg, setCallMsg] = useState('')
  const [calling, setCalling] = useState(false)

  if (ov.loading && !ov.data) return <Loading />
  if (ov.error) return <ErrorNote message={ov.error} />
  const o = ov.data!
  const trend = tr.data
  const last = o.last_scored_call
  const a = last?.analysis
  const name = parent.address_term

  const anchor = anchorDate()

  const mismatchRun = trend ? trailingMismatches(trend) : 0
  const usual = compareToUsual(o)

  const callNow = async () => {
    setCalling(true)
    setCallMsg('')
    try {
      const c = await api<Call>(`/api/parents/${parent.id}/call-now`, { method: 'POST' })
      setCallMsg(c.status === 'failed' ? `Couldn't place the call: ${c.error}` : `Calling ${name} now. Her phone should ring in a few seconds.`)
      ov.reload()
    } catch (e) {
      setCallMsg(e instanceof DemoActionError ? e.message : (e as Error).message)
    } finally {
      setCalling(false)
    }
  }

  return (
    <div className="today">
     <div className="today-main">
      <section className="blk-hero" aria-labelledby="answer">
        {last && a ? (
          <>
            <p className="meta">
              {fmtDay(last.scheduled_at, anchor)}'s call at {fmtTime(last.scheduled_at)}
              {last.duration_s ? `, ${fmtDuration(last.duration_s)}` : ''}
            </p>
            <h1 className="answer" id="answer">{a.headline || `${name} had her check-in call.`}</h1>
            <div className="when">
              <span className="mood-tag"><i style={{ background: moodColor(a.mood_score) }} />{moodWord(a.mood_score)}</span>
              {usual && <span className="muted">{usual}</span>}
            </div>
            {o.latest_call && o.latest_call.id !== last.id && <LatestNotScored call={o.latest_call} name={name} />}

            {mismatchRun > 0 && (
              <div className="callout" style={{ marginTop: 22 }}>
                <span className="callout-icon"><IconVoice /></span>
                <p>
                  <strong>
                    {mismatchRun === 1
                      ? 'She said she was fine, but her voice sounded low.'
                      : `She said she was fine, but her voice sounded low on the last ${mismatchRun} calls.`}
                  </strong>{' '}
                  <Link to={`/calls/${last.id}`}>Hear what she said</Link>
                </p>
              </div>
            )}
          </>
        ) : (
          <>
            <h1 className="answer" id="answer">No calls with {name} yet.</h1>
            <p className="muted">Saath calls her every evening at {fmtCallTime(parent.call_time)}. Her first summary will appear here.</p>
          </>
        )}
      </section>

        {trend && (
          <section className="evenings blk-strip" aria-labelledby="evenings-h">
            <div className="evenings-head">
              <h2 className="h2" id="evenings-h">The last two weeks</h2>
              <div style={{ display: 'flex', gap: 4 }}>
                <Link to="/week" className="btn btn-text btn-sm">Her week</Link>
                <Link to="/calls" className="btn btn-text btn-sm">All calls</Link>
              </div>
            </div>
            <Evenings points={trend.points} baseline={trend.stats.baseline} anchor={anchor} callTime={parent.call_time} name={name} selectedId={last?.id} />
            <EveningsLegend />
          </section>
        )}

        {a && (
          <section className="blk-basics" aria-labelledby="basics-h">
            <h2 className="h2" id="basics-h">From the last call</h2>
            <Basics a={a} />
          </section>
        )}
     </div>

      <aside className="today-side" aria-label="Alerts and tonight's call">
        <section className="side-block blk-alerts" aria-labelledby="alerts-h">
          <h2 className="h2" id="alerts-h">{o.unseen_alerts.length ? 'Needs you' : 'Alerts'}</h2>
          {o.unseen_alerts.length === 0 && <p className="empty">Nothing needs you right now. Saath will tell you here if her mood keeps dropping or something urgent comes up.</p>}
          {o.unseen_alerts.slice(0, 2).map((al) => (
            <AlertCard key={al.id} alert={al} parent={parent} anchor={anchor} onSeen={() => { ov.reload(); setUnseen(Math.max(0, o.unseen_alerts.length - 1)) }} />
          ))}
          {o.unseen_alerts.length > 2 && <Link to="/alerts" className="btn btn-text btn-sm">{o.unseen_alerts.length - 2} more <IconArrow /></Link>}
        </section>

        <div className="blk-msg">
          <MessageCard parent={parent} anchor={anchor} />
        </div>

        <section className="nextcall blk-next" aria-labelledby="next-h">
          <h2 className="h2" id="next-h">Tonight at {fmtCallTime(parent.call_time)}</h2>
          <p>
            {o.next_call?.tone === 'gentle'
              ? `Saath will go slower and more gently, and ask ${name} how she's really feeling.`
              : `Saath will keep the call warm and light.`}
          </p>
          {o.next_call && (o.next_call.open_threads.length > 0 || o.next_call.meds_to_check.length > 0) && (
            <ul>
              {o.next_call.meds_to_check.map((m) => (
                <li key={`m-${m}`}><IconArrow />Ask first about her {m}</li>
              ))}
              {o.next_call.open_threads.map((t) => (
                <li key={t}><IconArrow />Ask about: {t}</li>
              ))}
            </ul>
          )}
          <div className="nextcall-row">
            <button className="btn btn-quiet btn-sm" onClick={callNow} disabled={calling}>
              <IconPhone /> {calling ? 'Calling…' : 'Call her now'}
            </button>
            <Link to="/test-call" className="btn btn-quiet btn-sm">Try it in your browser</Link>
          </div>
          {callMsg && <p className="toast" role="status">{callMsg}</p>}
        </section>
      </aside>
    </div>
  )
}
