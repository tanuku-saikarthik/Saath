import { useState } from 'react'
import { apiUrl } from '../api'

/** Shown when the server has APP_PASSWORD set and this browser hasn't signed in. */
export function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      const r = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pw }),
      })
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? 'Could not sign in.')
      onDone()
    } catch (ex) {
      setErr((ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="main" style={{ maxWidth: 420, margin: '12vh auto 0', padding: '0 16px' }}>
      <h1 className="page-title">Saath</h1>
      <p className="hint" style={{ margin: '0 0 14px' }}>Enter the family password to continue.</p>
      <form className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="pw">Password</label>
          <input id="pw" type="password" autoComplete="current-password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} />
        </div>
        {err && <p className="error" role="alert">{err}</p>}
        <button className="btn btn-primary" type="submit" disabled={busy || !pw}>{busy ? 'Checking…' : 'Sign in'}</button>
      </form>
    </main>
  )
}
