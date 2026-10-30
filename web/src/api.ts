import { useCallback, useEffect, useState } from 'react'
import snapshot from './demo/snapshot.json'

// ---------- types (mirror backend/app/api.py) ----------

export type Medicine = { id?: number; name: string; timing: string; reminder_time?: string }
export type Parent = {
  id: number
  name: string
  address_term: string
  phone: string
  language: 'te' | 'hi'
  call_time: string
  topics: string[]
  consent_status: 'pending' | 'granted' | 'declined'
  child_name: string
  child_phone: string
  notify_kinds: AlertKind[]
  neighbours?: { name: string; phone: string }[]
  bolna_sync?: string[]
  medicines: Medicine[]
}
export type AlertKind = 'urgent' | 'sos' | 'drop' | 'recurring' | 'voice' | 'missed'
export type Note = {
  id: number
  text: string
  created_at: string
  call_id: number | null
  delivered_at: string | null
  reply: string
  pending: boolean
  is_question?: boolean
}
export type Emotion = { label: string; score: number }
export type Evidence = { quote_original: string; quote_en: string; signal: string }
export type Meals = { breakfast: string; lunch: string; dinner: string; note: string }
export type MedStatus = { name: string; status: string }
export type Analysis = {
  source: string
  text_emotions: Emotion[]
  text_valence: number
  arousal: number
  claimed_fine: boolean
  evidence: Evidence[]
  voice_probs: Record<string, number>
  voice_valence: number | null
  voice_source: string
  voice_segments: { start: number; end: number; top: string; valence: number | null }[]
  mood_score: number
  mismatch: boolean
  meals: Meals
  meds: MedStatus[]
  worries: string[]
  health_mentions: string[]
  topics: string[]
  open_threads: string[]
  emergency: boolean
  emergency_reason: string
  headline: string
  summary: string
  transcript_en: string
  message_delivered?: boolean
  reply_to_child?: string
  prosody?: Prosody
  prosody_usual?: Partial<Record<'pace_cps' | 'mean_pause_s' | 'loudness_db' | 'pitch_var_st', number>>
}
/** How she spoke, measured from her own audio (or pace only, from Bolna's speaking time). */
export type Prosody = {
  source?: 'audio' | 'speaking_time'
  speech_s?: number
  pace_cps?: number
  pause_ratio?: number
  mean_pause_s?: number
  loudness_db?: number
  pitch_hz?: number
  pitch_var_st?: number
}
export type CallKind = 'daily' | 'intro' | 'retry' | 'reminder' | 'inbound' | 'callback'
export type Call = {
  id: number
  kind: CallKind
  attempt: number
  status: string
  scheduled_at: string
  duration_s: number
  is_seeded: boolean
  has_audio: boolean
  error: string
  headline: string
  mood_score: number | null
  mismatch: boolean
  transferred?: boolean
  reminder_for?: string
  transcript?: string
  analysis?: Analysis | null
  notes?: Note[]
}
export type Alert = {
  id: number
  kind: AlertKind
  title: string
  reason: string
  talking_points: string[]
  call_id: number | null
  created_at: string
  seen: boolean
  notified?: string
  notify_error?: string
}
export type Stats = { enough: boolean; baseline: number | null; recent: number | null; below: number; delta: number | null }
export type Overview = {
  parent: Parent
  latest_call: Call | null
  last_scored_call: Call | null
  stats: Stats
  unseen_alerts: Alert[]
  next_call: { tone: string; open_threads: string[]; meds_to_check: string[]; avoid_topics: string[] } | null
}
export type TrendPoint = {
  call_id: number
  date: string
  status: string
  is_seeded: boolean
  mood: number | null
  text_valence: number | null
  voice_valence: number | null
  mismatch: boolean
  alerts: string[]
}
export type Trend = { points: TrendPoint[]; stats: Stats }
export type Health = {
  ok: boolean
  bolna: boolean
  llm: boolean
  voice_model_installed: boolean
  alert_calls?: boolean
  alert_webhook?: boolean
  transfer_on_emergency?: boolean
  test_call?: boolean
  sos_number?: string
  demo?: boolean
}
export type WeekEvening = { date: string; status: 'completed' | 'missed' | 'none'; call_id: number | null; mood: number | null; mismatch: boolean }
export type Week = {
  from: string
  to: string
  sentence: string
  evenings: WeekEvening[]
  reached: number
  missed: number
  mood: number | null
  mood_word: string
  mood_prev: number | null
  mood_delta: number | null
  said_fine_sounded_low: number
  medicines: { name: string; asked: number; taken: number; missed: number; unclear: number }[]
  meals_skipped: { breakfast: number; lunch: number; dinner: number }
  reminders?: { name: string; placed: number; answered: number; taken: number }[]
  called_saath?: number
  voice_changes?: string[]
  top_feelings: Emotion[]
  topics: string[]
  alerts: Partial<Record<AlertKind, number>>
  brightest: { call_id: number; date: string; headline: string; mood: number } | null
  lowest: { call_id: number; date: string; headline: string; mood: number } | null
  messages: { text: string; reply: string; delivered: string }[]
}

// ---------- client with demo fallback ----------

const BASE: string = (import.meta.env.VITE_API_URL as string | undefined) ?? ''
const demoData = snapshot as Record<string, unknown>
let mode: 'unknown' | 'live' | 'demo' = 'unknown'
let modePromise: Promise<'live' | 'demo'> | null = null

export function apiUrl(path: string) {
  return BASE + path
}

/** True when the visitor chose the seeded-data tab on the landing page. */
export function seededForced(): boolean {
  try { return sessionStorage.getItem('saath_demo') === '1' } catch { return false }
}

/** Leave demo mode (used after a successful family sign-in). */
export function clearDemo() {
  try { sessionStorage.removeItem('saath_demo') } catch { /* ignore */ }
  mode = 'unknown'
  modePromise = null
}

/** Open the app on the seeded sample history, without a live backend. */
export function openSeededDemo() {
  try { sessionStorage.setItem('saath_demo', '1') } catch { /* private mode: still opens below */ }
  mode = 'demo'
}

export function detectMode(): Promise<'live' | 'demo'> {
  if (mode !== 'unknown') return Promise.resolve(mode)
  if (seededForced()) { mode = 'demo'; return Promise.resolve('demo') }
  if (!modePromise) {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 2500)
    modePromise = fetch(apiUrl('/api/health'), { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(() => (mode = 'live'))
      .catch(() => (mode = 'demo'))
      .finally(() => clearTimeout(t)) as Promise<'live' | 'demo'>
  }
  return modePromise
}

export const isDemo = () => mode === 'demo'

/** "Now" for date labels. In the demo preview it's the evening after the latest sample call. */
export function anchorDate(): Date {
  if (mode !== 'demo') return new Date()
  const key = Object.keys(demoData).find((k) => /\/calls\?/.test(k))
  const calls = key ? (demoData[key] as { scheduled_at: string }[]) : []
  if (!calls.length) return new Date()
  const d = new Date(calls[0].scheduled_at)
  d.setDate(d.getDate() + 1)
  return d
}

function demoGet<T>(path: string): T {
  if (path in demoData) return structuredClone(demoData[path]) as T
  const base = path.split('?')[0]
  const key = Object.keys(demoData).find((k) => k.split('?')[0] === base)
  if (key) return structuredClone(demoData[key]) as T
  throw new Error('This screen needs the Saath backend. Start it and reload.')
}

export class DemoActionError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const m = await detectMode()
  if (m === 'demo') {
    if (!init || !init.method || init.method === 'GET') return demoGet<T>(path)
    if (path.startsWith('/api/alerts/') && path.endsWith('/seen')) {
      // Keep the demo feeling alive: remember read alerts in memory.
      const id = Number(path.split('/')[3])
      for (const key of Object.keys(demoData)) {
        const v = demoData[key] as Record<string, unknown>
        if (key.endsWith('/overview')) v.unseen_alerts = (v.unseen_alerts as Alert[]).filter((a) => a.id !== id)
        if (key.endsWith('/alerts')) (v as unknown as Alert[]).forEach((a) => a.id === id && (a.seen = true))
      }
      return {} as T
    }
    throw new DemoActionError('This is the demo preview. Run the Saath backend to place calls and save changes.')
  }
  const res = await fetch(apiUrl(path), {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event('saath-signin'))
    throw new Error('Sign in first.')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ? String(body.detail) : `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const load = useCallback(() => {
    if (!path) return
    setLoading(true)
    api<T>(path)
      .then((d) => {
        setData(d)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [path])
  useEffect(load, [load])
  return { data, error, loading, reload: load }
}

// ---------- dates (always shown in India time) ----------

const TZ = 'Asia/Kolkata'

export function dayKey(iso: string | Date) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(
    typeof iso === 'string' ? new Date(iso) : iso,
  )
}

export function fmtTime(iso: string) {
  return new Intl.DateTimeFormat('en-IN', { timeZone: TZ, hour: 'numeric', minute: '2-digit', hour12: true })
    .format(new Date(iso))
    .toLowerCase()
}

export function fmtDay(iso: string, anchor = new Date()) {
  const k = dayKey(iso)
  const today = dayKey(anchor)
  const y = new Date(anchor)
  y.setDate(y.getDate() - 1)
  if (k === today) return 'Today'
  if (k === dayKey(y)) return 'Yesterday'
  return new Intl.DateTimeFormat('en-IN', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'short' }).format(new Date(iso))
}

export function fmtCallTime(hhmm: string) {
  const [h, m] = hhmm.split(':').map(Number)
  const suffix = h >= 12 ? 'pm' : 'am'
  const hr = h % 12 === 0 ? 12 : h % 12
  return `${hr}:${String(m).padStart(2, '0')} ${suffix}`
}

export function fmtDuration(s: number) {
  if (!s) return ''
  const m = Math.round(s / 60)
  return m <= 1 ? 'about a minute' : `${m} minutes`
}

export const authStatus = () =>
  fetch(apiUrl('/api/auth/status'), { credentials: 'include' }).then((r) => r.json() as Promise<{ required: boolean; authed: boolean }>)
