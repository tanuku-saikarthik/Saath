import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { anchorDate, apiUrl, fmtDay, fmtDuration, fmtTime, useApi, type Analysis, type Call } from '../api'
import { useParent } from '../App'
import { IconBack } from '../components/Icons'
import { Basics, ErrorNote, Loading } from '../components/Pieces'
import { EMOTION_WORDS, moodColor, moodWord, VOICE_WORDS } from '../mood'

function Track({ value }: { value: number }) {
  const left = ((Math.max(-1, Math.min(1, value)) + 1) / 2) * 100
  return (
    <div className="track" role="img" aria-label={`${moodWord(value)} (${value.toFixed(2)} on a scale from −1 to +1)`}>
      <span className="track-mid" />
      <span className="track-dot" style={{ left: `${left}%` }} />
    </div>
  )
}

function parseTurns(t: string) {
  return t
    .split('\n')
    .map((ln) => ln.trim())
    .filter(Boolean)
    .map((ln) => {
      const i = ln.indexOf(':')
      const who = ln.slice(0, i).toLowerCase()
      return { who: who === 'user' ? 'parent' : 'saath', text: ln.slice(i + 1).trim() }
    })
}

type SignalKey = 'pace_cps' | 'mean_pause_s' | 'loudness_db' | 'pitch_var_st'
const SIGNALS: { key: SignalKey; name: string; fmt: (v: number) => string; lowerIs: string; higherIs: string; strainedIf: 'lower' | 'higher'; notable: (now: number, usual: number) => boolean }[] = [
  { key: 'pace_cps', name: 'Speaking pace', fmt: (v) => `${v.toFixed(1)} letters a second`, lowerIs: 'slower', higherIs: 'faster', strainedIf: 'lower', notable: (n, u) => Math.abs(n - u) / u >= 0.15 },
  { key: 'mean_pause_s', name: 'Pauses', fmt: (v) => `${v.toFixed(2)} s on average`, lowerIs: 'shorter', higherIs: 'longer', strainedIf: 'higher', notable: (n, u) => Math.abs(n - u) / u >= 0.2 && Math.abs(n - u) >= 0.15 },
  { key: 'loudness_db', name: 'Loudness', fmt: (v) => `${v.toFixed(0)} dB`, lowerIs: 'quieter', higherIs: 'louder', strainedIf: 'lower', notable: (n, u) => Math.abs(n - u) >= 4 },
  { key: 'pitch_var_st', name: 'Pitch movement', fmt: (v) => `${v.toFixed(1)} semitones`, lowerIs: 'flatter', higherIs: 'livelier', strainedIf: 'lower', notable: (n, u) => Math.abs(n - u) / u >= 0.25 },
]

function HowSheSpoke({ a, name }: { a: Analysis; name: string }) {
  const p = a.prosody ?? {}
  const usual = a.prosody_usual ?? {}
  const rows = SIGNALS.filter((s) => typeof p[s.key] === 'number')
  if (!rows.length) return null
  return (
    <section className="section" aria-labelledby="spoke-h">
      <h2 className="h2" id="spoke-h">How she spoke</h2>
      <div className="spoke">
        {rows.map((s) => {
          const now = p[s.key] as number
          const u = usual[s.key]
          let diff = 'Not enough calls yet to know her usual'
          let off = false
          if (typeof u === 'number' && u !== 0) {
            const notable = s.notable(now, u)
            const dir = now < u ? s.lowerIs : s.higherIs
            diff = !notable ? 'About her usual' : s.key === 'loudness_db' ? `${Math.abs(now - u).toFixed(0)} dB ${dir} than usual` : `${Math.round((Math.abs(now - u) / u) * 100)}% ${dir} than usual`
            off = notable && ((now < u && s.strainedIf === 'lower') || (now > u && s.strainedIf === 'higher'))
          }
          return (
            <div className="spoke-row" key={s.key}>
              <span className="spoke-name">{s.name}</span>
              <span className="spoke-val">{s.fmt(now)}</span>
              <span className={`spoke-diff${off ? ' off' : ''}`}>{diff}</span>
            </div>
          )
        })}
      </div>
      <p className="meta small" style={{ marginTop: 10 }}>
        {p.source === 'speaking_time'
          ? `Pace from how long ${name} spoke on the call. Her own audio wasn't on a separate channel, so pauses, loudness and pitch weren't measured.`
          : `Measured from ${name}'s own voice and compared only with her usual. Changes over several calls can mean tiredness, a cold or feeling low. This is not a medical test.`}
      </p>
    </section>
  )
}

const STATUS_TEXT: Record<string, string> = {
  missed: "She didn't pick up.",
  failed: "The call couldn't be placed.",
  queued: 'Saath is placing this call.',
  in_progress: 'This call is in progress.',
  processing: 'The call has ended. Saath is listening back to it.',
}

export default function CallDetail() {
  const { id } = useParams()
  const { parent } = useParent()
  const { data: c, error, loading } = useApi<Call>(`/api/calls/${id}`)
  const [lang, setLang] = useState<'orig' | 'en'>('orig')

  if (loading && !c) return <Loading />
  if (error) return <ErrorNote message={error} />
  if (!c) return null
  const a = c.analysis
  const name = parent.address_term
  const langCode = parent.language
  const langName = langCode === 'hi' ? 'Hindi' : 'Telugu'
  const anchor = anchorDate()

  const voiceTop = a
    ? Object.entries(a.voice_probs).filter(([k, v]) => v > 0.02 && k !== 'other' && k !== 'unknown').sort((x, y) => y[1] - x[1]).slice(0, 4)
    : []
  const turns = parseTurns(lang === 'orig' ? c.transcript ?? '' : a?.transcript_en ?? '')

  return (
    <article className="detail">
      <Link to="/calls" className="back"><IconBack /> All calls</Link>
      <p className="meta">
        {fmtDay(c.scheduled_at, anchor)}, {fmtTime(c.scheduled_at)}
        {c.duration_s ? `, ${fmtDuration(c.duration_s)}` : ''}
        {c.kind === 'retry' ? ', second try' : ''}
        {c.kind === 'reminder' ? `, ${c.reminder_for || 'medicine'} reminder` : ''}
        {c.kind === 'inbound' ? `, ${name} called Saath` : ''}
        {c.kind === 'callback' ? ', Saath called her back' : ''}
      </p>
      <h1 className="answer" style={{ maxWidth: '26ch' }}>{a?.headline || STATUS_TEXT[c.status] || 'Check-in call'}</h1>
      <div className="when">
        {a && <span className="mood-tag"><i style={{ background: moodColor(a.mood_score) }} />{moodWord(a.mood_score)}</span>}
        {c.is_seeded && <span className="pill seeded">Sample history</span>}
        {a?.source === 'mock' && <span className="pill warn">Rough estimate (no LLM key)</span>}
        {a?.emergency && <span className="pill bad">Urgent: {a.emergency_reason}</span>}
        {c.transferred && <span className="pill">Saath connected her to you</span>}
      </div>
      {c.status === 'failed' && c.error && <p className="error" style={{ marginTop: 12 }}>{c.error}</p>}

      {a && c.kind === 'reminder' && (
        <section className="section" aria-labelledby="bas-h">
          <h2 className="h2" id="bas-h">Medicine</h2>
          <Basics a={{ ...a, topics: [], health_mentions: a.health_mentions ?? [], meals: { breakfast: 'not_discussed', lunch: 'not_discussed', dinner: 'not_discussed', note: '' } }} />
          <p className="meta small" style={{ marginTop: 10 }}>A short reminder call. It doesn't count toward her mood.</p>
        </section>
      )}

      {a && c.kind !== 'reminder' && (
        <>
          <section className="section" aria-labelledby="sig-h">
            <h2 className="h2" id="sig-h">Words and voice</h2>
            <div className="signals">
              <div className="signal-row">
                <div className="signal-label">What she said<small>From her words</small></div>
                <Track value={a.text_valence} />
              </div>
              <div className="signal-row">
                <div className="signal-label">How she sounded<small>From her voice</small></div>
                {a.voice_valence === null ? <span className="muted small">Voice not analysed for this call</span> : <Track value={a.voice_valence} />}
              </div>
              <div className="signal-row" style={{ marginTop: -8 }} aria-hidden="true">
                <span />
                <div className="track-ends"><span>Low</span><span>Bright</span></div>
              </div>
              {a.mismatch ? (
                <p className="signal-note"><strong>Her words and her voice disagree.</strong> She said she was fine, but she sounded {a.voice_valence !== null && a.voice_valence <= -0.5 ? 'quite low' : 'low'}.</p>
              ) : a.voice_valence !== null ? (
                <p className="signal-note">Her words and her voice tell the same story.</p>
              ) : null}
            </div>
          </section>

          <HowSheSpoke a={a} name={name} />

          <section className="section two" aria-label="Emotion breakdown">
            <div>
              <h3 className="h3">In her words</h3>
              <div className="bars">
                {a.text_emotions.slice(0, 5).map((e) => (
                  <div className="bar-row" key={e.label}>
                    <span>{EMOTION_WORDS[e.label] ?? e.label}</span>
                    <span className="bar"><i style={{ width: `${e.score * 100}%` }} /></span>
                    <span className="bar-val">{Math.round(e.score * 100)}</span>
                  </div>
                ))}
              </div>
            </div>
            {voiceTop.length > 0 && (
              <div>
                <h3 className="h3">In her voice</h3>
                <div className="bars">
                  {voiceTop.map(([k, v]) => (
                    <div className="bar-row" key={k}>
                      <span>{VOICE_WORDS[k] ?? k}</span>
                      <span className="bar"><i style={{ width: `${v * 100}%`, background: 'var(--ink-3)' }} /></span>
                      <span className="bar-val">{Math.round(v * 100)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          {a.evidence.length > 0 && (
            <section className="section" aria-labelledby="ev-h">
              <h2 className="h2" id="ev-h">In her own words</h2>
              <div className="quotes">
                {a.evidence.map((ev, i) => (
                  <blockquote className="quote" key={i} style={{ margin: 0 }}>
                    <p className="quote-orig" lang={langCode}>{ev.quote_original}</p>
                    <p className="quote-en">{ev.quote_en}</p>
                    {ev.signal && <div className="quote-sig"><span className="pill">{EMOTION_WORDS[ev.signal] ?? ev.signal}</span></div>}
                  </blockquote>
                ))}
              </div>
            </section>
          )}

          {(c.notes?.length ?? 0) > 0 && (
            <section className="section" aria-labelledby="note-h">
              <h2 className="h2" id="note-h">Your message</h2>
              {c.notes!.map((n) => (
                <div className="msg msg-thread" key={n.id}>
                  <p className="msg-you"><span className="msg-who">You asked Saath to tell her</span>{n.text}</p>
                  {n.reply && <p className="msg-her"><span className="msg-who">{name} replied</span>{n.reply}</p>}
                </div>
              ))}
            </section>
          )}

          <section className="section" aria-labelledby="bas-h">
            <h2 className="h2" id="bas-h">Meals and medicines</h2>
            <Basics a={a} />
          </section>
        </>
      )}

      {(c.transcript || a?.transcript_en) && (
        <section className="section" aria-labelledby="convo-h">
          <div className="convo-head">
            <h2 className="h2" id="convo-h" style={{ margin: 0 }}>The conversation</h2>
            {a?.transcript_en && (
              <div className="seg" role="group" aria-label="Transcript language">
                <button aria-pressed={lang === 'orig'} onClick={() => setLang('orig')}>{langName}</button>
                <button aria-pressed={lang === 'en'} onClick={() => setLang('en')}>English</button>
              </div>
            )}
          </div>
          {c.has_audio && <audio controls src={apiUrl(`/api/calls/${c.id}/audio`)} />}
          <div className="convo" style={{ marginTop: 12 }}>
            {turns.map((t, i) => (
              <div key={i} className={`turn ${t.who}`} lang={lang === 'orig' ? langCode : 'en'}>
                <span className="turn-who">{t.who === 'parent' ? name : 'Saath'}</span>
                {t.text}
              </div>
            ))}
          </div>
        </section>
      )}
    </article>
  )
}
