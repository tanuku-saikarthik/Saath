import { useState } from 'react'
import { apiUrl, openSeededDemo } from '../api'

/** Landing page when the server has APP_PASSWORD set and this browser hasn't signed in.
 *  Two tabs: "Set up" (steps on the left, family password on the right) and "Seeded data" (sample family, no backend needed). */
export function Login({ onDone }: { onDone: () => void }) {
  const [tab, setTab] = useState<'setup' | 'seeded'>('setup')
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

  const seeded = () => {
    openSeededDemo()
    onDone()
  }

  return (
    <main className="main login-landing">
      <h1 className="page-title">Saath</h1>
      <p className="hint" style={{ margin: '0 0 14px' }}>A daily call that hears how she really is.</p>
      <div className="login-tabs" role="tablist" aria-label="Start here">
        <button role="tab" aria-selected={tab === 'setup'} className={tab === 'setup' ? 'on' : ''} onClick={() => setTab('setup')}>Set up</button>
        <button role="tab" aria-selected={tab === 'seeded'} className={tab === 'seeded' ? 'on' : ''} onClick={() => setTab('seeded')}>Try the demo</button>
      </div>

      {tab === 'setup' && (
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
      )}

      {tab === 'seeded' && (
        <section className="fieldset" aria-labelledby="seed-h">
          <h2 className="h2" id="seed-h">Explore a sample family</h2>
          <p className="hint" style={{ margin: '0 0 12px' }}>
            Two weeks of sample evenings for a parent, with calls, alerts, a week view, and her phone page. Nothing here calls anyone or saves changes.
          </p>
          <button className="btn btn-primary" type="button" onClick={seeded}>Open the demo</button>
        </section>
      )}
    </main>
  )
}
