import { useState } from 'react'
import { apiUrl } from '../api'

/** Landing page when the server has APP_PASSWORD set and this browser hasn't signed in.
 *  Left: what Setup does. Right: the family password to sign in. */
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
    <main className="main login-landing">
      <h1 className="page-title">Saath</h1>
      <p className="hint" style={{ margin: '0 0 18px' }}>A daily call that hears how she really is.</p>
      <div className="login-grid">
        <section className="fieldset" aria-labelledby="setup-h">
          <h2 className="h2" id="setup-h">Set up Saath for a parent</h2>
          <ol className="login-steps">
            <li><strong>About her:</strong> her name, what Saath should call her, her phone and language.</li>
            <li><strong>Medicines and topics:</strong> medicine names and times, and what to ask about.</li>
            <li><strong>Daily call:</strong> the evening time Saath should call her.</li>
          </ol>
          <p className="hint" style={{ margin: '12px 0 0' }}>Setup opens after you sign in with the family password on the right.</p>
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
