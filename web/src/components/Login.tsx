import { useState } from 'react'
import { apiUrl, clearDemo, openSeededDemo } from '../api'

/** Setup page: opened from the Setup button in the demo menu. Steps on the left; family password on the right. */
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
      clearDemo()
      onDone()
    } catch (ex) {
      setErr((ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const back = () => {
    openSeededDemo()
    onDone()
  }

  return (
    <main className="main login-landing">
      <div className="login-head">
        <h1 className="page-title">Saath</h1>
        <button type="button" className="btn btn-text btn-sm" onClick={back}>Back to the demo</button>
      </div>
      <p className="hint" style={{ margin: '0 0 14px' }}>A daily call that hears how she really is.</p>
      <div className="login-grid">
        <section className="fieldset" aria-labelledby="setup-h">
          <h2 className="h2" id="setup-h">Set up Saath for a parent</h2>
          <ol className="login-steps">
            <li><strong>About her:</strong> her name, what Saath should call her, her phone and language.</li>
            <li><strong>Medicines and topics:</strong> medicine names and times, and what to ask about.</li>
            <li><strong>Daily call:</strong> the evening time Saath should call her.</li>
          </ol>
          <p className="hint" style={{ margin: '12px 0 0' }}>Her number must be verified in Bolna while we are on the trial account.</p>
        </section>
        <section className="fieldset" aria-labelledby="signin-h">
          <h2 className="h2" id="signin-h">Already set up?</h2>
          <p className="hint" style={{ margin: '0 0 12px' }}>Enter the family password to open the app.</p>
          <form className="form" onSubmit={submit}>
            <div className="field">
              <label htmlFor="pw">Family password</label>
              <input id="pw" type="password" autoComplete="current-password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} />
            </div>
            {err && <p className="error" role="alert">{err}</p>}
            <button className="btn btn-primary" type="submit" disabled={busy || !pw}>{busy ? 'Checking…' : 'Sign in'}</button>
          </form>
        </section>
      </div>
    </main>
  )
}
