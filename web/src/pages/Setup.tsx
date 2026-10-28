import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, DemoActionError } from '../api'
import { AboutFields, MedicineFields, medsPayload, TimeField, toPayload, type ParentDraft } from '../components/ParentFields'

const STEPS = ['About her', 'Medicines and topics', 'Daily call']

export default function Setup({ onDone }: { onDone: () => void }) {
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [child, setChild] = useState('')
  const [childPhone, setChildPhone] = useState('')
  const [d, setD] = useState<ParentDraft>({
    name: '', address_term: '', phone: '', language: 'te', call_time: '19:00', topics: '', medicines: [{ name: '', timing: '' }],
  })
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)

  const next = (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    if (step < STEPS.length - 1) return setStep(step + 1)
    submit()
  }

  const submit = async () => {
    setSaving(true)
    try {
      await api('/api/parents', {
        method: 'POST',
        body: JSON.stringify({ child_name: child.trim(), child_phone: childPhone.replace(/\s+/g, ''), parent: toPayload(d), medicines: medsPayload(d), place_intro_call: true }),
      })
      onDone()
      nav('/')
    } catch (ex) {
      setErr(ex instanceof DemoActionError ? ex.message : (ex as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <h1 className="answer" style={{ marginTop: 16 }}>Set up a daily call for your parent</h1>
      <p className="muted" style={{ marginTop: -4, marginBottom: 20 }}>
        Saath calls her every evening in Telugu or Hindi, asks about her day, meals and medicines, and tells you how she's really doing.
      </p>
      <ol className="steps" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
        {STEPS.map((s, i) => <li key={s} className={i <= step ? 'done' : ''}><span className="sr-only">{s}</span></li>)}
      </ol>
      <form className="form" onSubmit={next} style={{ marginTop: 16 }}>
        <fieldset className="fieldset">
          <legend>{STEPS[step]}</legend>
          {step === 0 && (
            <>
              <div className="field">
                <label htmlFor="child">Your name</label>
                <input id="child" value={child} onChange={(e) => setChild(e.target.value)} required />
                <span className="hint">Saath tells her you set up the calls.</span>
              </div>
              <div className="field">
                <label htmlFor="childphone">Your phone number</label>
                <input id="childphone" type="tel" inputMode="tel" value={childPhone} placeholder="+91 98765 43210" onChange={(e) => setChildPhone(e.target.value)} />
                <span className="hint">So Saath can call you with an alert, or connect her to you in an emergency.</span>
              </div>
              <AboutFields d={d} set={setD} />
            </>
          )}
          {step === 1 && <MedicineFields d={d} set={setD} />}
          {step === 2 && (
            <>
              <TimeField d={d} set={setD} />
              <p className="muted small" style={{ margin: 0 }}>
                When you save, Saath places a short intro call. It explains who it is and asks her if daily calls are okay. Calls start only if she agrees.
              </p>
            </>
          )}
        </fieldset>
        <div className="form-actions">
          {step > 0 && <button type="button" className="btn btn-quiet" onClick={() => setStep(step - 1)}>Back</button>}
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {step < STEPS.length - 1 ? 'Continue' : saving ? 'Saving…' : 'Save and place intro call'}
          </button>
          {err && <p className="error" role="alert">{err}</p>}
        </div>
      </form>
    </div>
  )
}
