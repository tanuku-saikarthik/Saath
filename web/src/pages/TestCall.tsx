import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { apiUrl, isDemo } from '../api'
import { useParent } from '../App'
import { IconBack, IconPhone } from '../components/Icons'

type Turn = { who: 'saath' | 'parent'; text: string }
type Phase = 'idle' | 'starting' | 'saath' | 'ready' | 'recording' | 'sending' | 'ending' | 'done' | 'error'
type Kind = 'daily' | 'reminder' | 'inbound'
const KINDS: [Kind, string][] = [['daily', 'Evening check-in'], ['reminder', 'Medicine reminder'], ['inbound', 'She calls Saath']]

async function post<T>(path: string, body?: BodyInit, json = true): Promise<T> {
  const res = await fetch(apiUrl(path), {
    credentials: 'include',
    method: 'POST',
    body,
    headers: json && body ? { 'Content-Type': 'application/json' } : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail ? String(data.detail) : `Request failed (${res.status})`)
  return data as T
}

function pickMime() {
  const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  return options.find((m) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m)) ?? ''
}

export default function TestCall() {
  const { parent } = useParent()
  const nav = useNavigate()
  const [phase, setPhase] = useState<Phase>('idle')
  const [turns, setTurns] = useState<Turn[]>([])
  const [error, setError] = useState('')
  const [secs, setSecs] = useState(0)
  const [carrying, setCarrying] = useState('')
  const [urgent, setUrgent] = useState<{ reason: string; transfer: boolean } | null>(null)
  const [childPhone, setChildPhone] = useState('')
  const callId = useRef<number | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const stream = useRef<MediaStream | null>(null)
  const player = useRef<HTMLAudioElement | null>(null)
  const name = parent.address_term
  const langCode = parent.language
  const [params] = useSearchParams()
  const [kind, setKind] = useState<Kind>((['daily', 'reminder', 'inbound'] as Kind[]).find((k) => k === params.get('kind')) ?? 'daily')
  const meds = parent.medicines
  const [medicine, setMedicine] = useState(meds.find((m) => m.reminder_time)?.name ?? meds[0]?.name ?? '')

  useEffect(() => () => {
    stream.current?.getTracks().forEach((t) => t.stop())
    player.current?.pause()
  }, [])

  useEffect(() => {
    if (phase !== 'recording') return
    setSecs(0)
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [phase])

  const play = (b64: string) =>
    new Promise<void>((resolve) => {
      setPhase('saath')
      const a = new Audio(`data:audio/mpeg;base64,${b64}`)
      player.current = a
      a.onended = () => resolve()
      a.onerror = () => resolve() // still let the call continue if playback fails
      a.play().catch(() => resolve())
    })

  const fail = (e: unknown) => {
    setError(e instanceof Error ? e.message : String(e))
    setPhase('error')
  }

  const start = async () => {
    setError('')
    setTurns([])
    setUrgent(null)
    setPhase('starting')
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      return fail(new Error('Saath needs your microphone. Allow mic access in the browser and try again.'))
    }
    try {
      const r = await post<{ call_id: number; reply_text: string; reply_audio: string; child_message: string; child_phone: string }>(
        '/api/test-call/start', JSON.stringify({ parent_id: parent.id, kind, medicine }),
      )
      callId.current = r.call_id
      setCarrying(r.child_message)
      setChildPhone(r.child_phone)
      setTurns([{ who: 'saath', text: r.reply_text }])
      await play(r.reply_audio)
      setPhase('ready')
    } catch (e) {
      stream.current?.getTracks().forEach((t) => t.stop())
      fail(e)
    }
  }

  const startTalking = () => {
    if (!stream.current) return
    chunks.current = []
    const mime = pickMime()
    const rec = new MediaRecorder(stream.current, mime ? { mimeType: mime } : undefined)
    rec.ondataavailable = (ev) => ev.data.size && chunks.current.push(ev.data)
    rec.onstop = () => void sendTurn(rec.mimeType)
    recorder.current = rec
    rec.start()
    setPhase('recording')
  }

  const stopTalking = () => recorder.current?.state === 'recording' && recorder.current.stop()

  const sendTurn = async (mime: string) => {
    setPhase('sending')
    const ext = mime.includes('mp4') ? 'm4a' : 'webm'
    const form = new FormData()
    form.append('audio', new Blob(chunks.current, { type: mime || 'audio/webm' }), `turn.${ext}`)
    try {
      const r = await post<{ heard: string; reply_text: string; reply_audio: string; urgent: string; transfer: boolean }>(`/api/test-call/${callId.current}/turn`, form, false)
      setTurns((t) => [...t, { who: 'parent', text: r.heard }, { who: 'saath', text: r.reply_text }])
      if (r.urgent) setUrgent({ reason: r.urgent, transfer: r.transfer })
      await play(r.reply_audio)
      setPhase('ready')
    } catch (e) {
      // A turn that didn't go through (too short, no words heard) shouldn't end the call.
      setError(e instanceof Error ? e.message : String(e))
      setPhase('ready')
    }
  }

  const end = async () => {
    player.current?.pause()
    stream.current?.getTracks().forEach((t) => t.stop())
    if (callId.current === null) return
    setPhase('ending')
    try {
      const r = await post<{ call_id: number; status: string }>(`/api/test-call/${callId.current}/end`)
      if (r.status === 'missed') return nav(`/calls/${r.call_id}`)
      for (let i = 0; i < 60; i++) {
        await new Promise((res) => setTimeout(res, 1500))
        const c = await fetch(apiUrl(`/api/calls/${r.call_id}`), { credentials: 'include' }).then((x) => x.json())
        if (['completed', 'failed', 'missed'].includes(c.status)) {
          setPhase('done')
          return nav(`/calls/${r.call_id}`)
        }
      }
      fail(new Error('Scoring is taking longer than expected. Check the call list in a minute.'))
    } catch (e) {
      fail(e)
    }
  }

  if (isDemo()) {
    return (
      <div style={{ maxWidth: 640 }}>
        <Link to="/" className="back"><IconBack /> Today</Link>
        <h1 className="page-title">Call from your computer</h1>
        <p className="empty" style={{ marginTop: 16 }}>
          Calling from your computer works in the live app, not in this preview. Open Saath from the running backend to try it.
        </p>
      </div>
    )
  }

  const live = ['saath', 'ready', 'recording', 'sending'].includes(phase)
  const status: Record<Phase, string> = {
    idle: '', starting: 'Connecting…', saath: 'Saath is speaking…', ready: `Your turn. Answer as ${name} would.`,
    recording: `Listening… ${secs}s`, sending: 'Saath is thinking…', ending: 'Call ended. Saath is listening back to it…',
    done: 'Done', error: '',
  }

  return (
    <div className="tc">
      <Link to="/" className="back"><IconBack /> Today</Link>
      <h1 className="page-title">Call from your computer</h1>
      <p className="muted" style={{ maxWidth: '60ch', margin: '8px 0 16px' }}>
        {kind === 'inbound'
          ? `Talk to Saath from ${name}'s side, as if she were calling any time of day. Saath answers already knowing her name, medicines and your latest message.`
          : kind === 'reminder'
            ? `Hear the short reminder call ${name} gets when a medicine is due. You answer as her.`
            : `Hear tonight's call as ${name} would.`}{' '}
        No phone needed: it runs in {langCode === 'hi' ? 'Hindi' : 'Telugu'} through this computer's mic. When you end the call, it's scored and added to her history like a real one.
      </p>
      {(phase === 'idle' || phase === 'error') && parent.consent_status === 'granted' && (
        <div className="kind-pick">
          <div className="seg" role="group" aria-label="Kind of call">
            {KINDS.map(([k, label]) => (
              <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}>{label}</button>
            ))}
          </div>
          {kind === 'reminder' && meds.length > 0 && (
            <select aria-label="Medicine to remind her about" value={medicine} onChange={(e) => setMedicine(e.target.value)} className="tc-select">
              {meds.map((m) => <option key={m.name} value={m.name}>{m.name}{m.reminder_time ? ` (${m.reminder_time})` : ''}</option>)}
            </select>
          )}
        </div>
      )}

      <section className="tc-screen" aria-live="polite">
        <div className="tc-who">
          <span className={`tc-avatar${phase === 'saath' ? ' speaking' : ''}`} aria-hidden="true">S</span>
          <div>
            <p className="tc-name">Saath</p>
            <p className="tc-status">{phase === 'idle' ? (kind === 'inbound' ? `${name} is calling Saath` : `Calling ${name} on ${parent.phone}`) : status[phase]}</p>
          </div>
        </div>

        <div className="tc-controls">
          {phase === 'idle' || phase === 'error' ? (
            <button className="tc-talk" onClick={start}><IconPhone /> Start call</button>
          ) : phase === 'recording' ? (
            <button className="tc-talk recording" onClick={stopTalking}>Tap when you're done</button>
          ) : (
            <button className="tc-talk" onClick={startTalking} disabled={phase !== 'ready'}>Tap to talk</button>
          )}
          {live && <button className="btn btn-quiet tc-end" onClick={end}>End call</button>}
        </div>
        {error && <p className="tc-error" role="alert">{error}</p>}
        {carrying && live && <p className="tc-note">Saath is carrying your message: "{carrying}"</p>}
      </section>

      {urgent && (
        <section className="tc-urgent" role="alert">
          <p className="tc-urgent-title">Possible {urgent.reason}. Saath raised an urgent alert the moment she said it.</p>
          <p>
            On a real phone call, Saath would now {urgent.transfer
              ? `connect ${name} to you live${childPhone ? ` on ${childPhone}` : ''}`
              : `call you${childPhone ? ` on ${childPhone}` : ''} with the alert`}
            . Calls from this computer don't ring any phone.
          </p>
        </section>
      )}

      {turns.length > 0 && (
        <section className="section" aria-label="Conversation so far">
          <div className="convo">
            {turns.map((t, i) => (
              <div key={i} className={`turn ${t.who}`} lang={langCode}>
                <span className="turn-who">{t.who === 'parent' ? `${name} (you)` : 'Saath'}</span>
                {t.text}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
