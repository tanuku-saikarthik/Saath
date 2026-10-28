import { useState } from 'react'
import { HerPhoneCard } from '../components/HerPhoneCard'
import { api, DemoActionError, useApi, type AlertKind, type Health, type Parent } from '../api'
import { useParent } from '../App'
import { AboutFields, MedicineFields, medsPayload, TimeField, toPayload, type ParentDraft } from '../components/ParentFields'

export default function Profile() {
  const { parent, refreshParent } = useParent()
  const [d, setD] = useState<ParentDraft>({
    name: parent.name,
    address_term: parent.address_term,
    phone: parent.phone,
    language: parent.language,
    call_time: parent.call_time,
    topics: parent.topics.join(', '),
    medicines: parent.medicines.map((m) => ({ name: m.name, timing: m.timing, reminder_time: m.reminder_time ?? '' })),
  })
  const [consent, setConsent] = useState(parent.consent_status)
  const [childName, setChildName] = useState(parent.child_name)
  const [childPhone, setChildPhone] = useState(parent.child_phone ?? '')
  const [neighbours, setNeighbours] = useState<{ name: string; phone: string }[]>(parent.neighbours ?? [])
  const setN = (i: number, k: 'name' | 'phone', v: string) => setNeighbours((ns) => ns.map((n, j) => (j === i ? { ...n, [k]: v } : n)))
  const [kinds, setKinds] = useState<AlertKind[]>(parent.notify_kinds ?? [])
  const toggle = (k: AlertKind) => setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]))
  const { data: health } = useApi<Health>('/api/health')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg('')
    setErr('')
    try {
      await api<Parent>(`/api/parents/${parent.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          ...toPayload(d), medicines: medsPayload(d), consent_status: consent,
          child_name: childName.trim(), child_phone: childPhone.replace(/\s+/g, ''), notify_kinds: kinds,
          neighbours: neighbours.filter((n) => n.phone.trim()),
        }),
      })
      setMsg('Changes saved. Tonight’s call will use them.')
      refreshParent()
    } catch (ex) {
      setErr(ex instanceof DemoActionError ? ex.message : (ex as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="page-head">
        <h1 className="page-title">{parent.address_term}</h1>
      </div>
      <form className="form" onSubmit={save}>
        <fieldset className="fieldset">
          <legend>About her</legend>
          <AboutFields d={d} set={setD} />
        </fieldset>
        <fieldset className="fieldset">
          <legend>Medicines and topics</legend>
          <MedicineFields d={d} set={setD} />
        </fieldset>
        <fieldset className="fieldset">
          <legend>Daily call</legend>
          <TimeField d={d} set={setD} />
          <div className="field">
            <span id="consent" style={{ fontWeight: 500, fontSize: 14, color: 'var(--ink-2)' }}>Has she agreed to daily calls?</span>
            <div className="radio-row" role="radiogroup" aria-labelledby="consent">
              <label><input type="radio" name="consent" checked={consent === 'granted'} onChange={() => setConsent('granted')} /> Yes</label>
              <label><input type="radio" name="consent" checked={consent === 'pending'} onChange={() => setConsent('pending')} /> Not yet</label>
              <label><input type="radio" name="consent" checked={consent === 'declined'} onChange={() => setConsent('declined')} /> No, pause calls</label>
            </div>
            <span className="hint">Saath only places daily calls once she has agreed. The intro call asks her.</span>
          </div>
        </fieldset>
        <fieldset className="fieldset">
          <legend>Her Saath number</legend>
          <div className="sos-box">
            {health?.sos_number ? (
              <>
                <p className="meta small" style={{ margin: 0 }}>Save this in her phone as “Saath”</p>
                <p className="sos-num" style={{ margin: '2px 0 6px' }}>{health.sos_number}</p>
              </>
            ) : (
              <p style={{ margin: '0 0 6px', fontWeight: 500 }}>No Saath number set up yet</p>
            )}
            <p className="small" style={{ margin: 0, color: 'var(--ink-2)' }}>
              {parent.address_term} can call this number any time, not just in the evening. Saath answers in {parent.language === 'hi' ? 'Hindi' : 'Telugu'}, already knowing her name, her medicines and your latest message.
              If she needs help, you're alerted and can be connected straight away. If the call drops before she speaks, Saath rings her back.
              {!health?.sos_number && ' To set it up, link a Bolna number to her agent for incoming calls and add it to .env as SOS_NUMBER.'}
            </p>
          </div>
        </fieldset>
        <fieldset className="fieldset">
          <legend>Alerts to you</legend>
          <div className="grid2">
            <div className="field">
              <label htmlFor="cname">Your name</label>
              <input id="cname" value={childName} onChange={(e) => setChildName(e.target.value)} required />
              <span className="hint">Saath tells {parent.address_term} the calls are from you.</span>
            </div>
            <div className="field">
              <label htmlFor="cphone">Your phone number</label>
              <input id="cphone" type="tel" inputMode="tel" value={childPhone} placeholder="+91 98765 43210" onChange={(e) => setChildPhone(e.target.value)} />
              <span className="hint">For alert calls, and to connect her to you in an emergency.</span>
            </div>
          </div>
          <div className="field">
            <span id="kinds" style={{ fontWeight: 500, fontSize: 14, color: 'var(--ink-2)' }}>Saath calls you when</span>
            <div className="checks" role="group" aria-labelledby="kinds">
              {([
                ['urgent', 'She mentions something urgent, like a fall or chest pain'],
                ['sos', 'She calls Saath herself'],
                ['drop', 'Her mood stays low for several calls'],
                ['recurring', 'She keeps sounding lonely or worried'],
                ['voice', 'Her voice sounds different from her usual for several calls'],
                ['missed', 'She misses a check-in'],
              ] as [AlertKind, string][]).map(([k, label]) => (
                <label key={k}><input type="checkbox" checked={kinds.includes(k)} onChange={() => toggle(k)} /> {label}</label>
              ))}
            </div>
            <span className="hint">Every alert also shows here in the app. Calls to you need the alert agent set up in Bolna.</span>
          </div>
        </fieldset>
        <HerPhoneCard parent={parent} />
        <fieldset className="fieldset">
          <legend>Emergency contacts</legend>
          <p className="hint" style={{ margin: '0 0 10px' }}>
            On an urgent alert, or if she calls Saath for help, Saath also rings these people on their ordinary phone numbers and asks them to check on {parent.address_term}. Add a neighbour or relative who lives close by. Up to 5.
          </p>
          {neighbours.map((n, i) => (
            <div className="grid2" key={i} style={{ marginBottom: 8, alignItems: 'end' }}>
              <div className="field">
                <label htmlFor={`nn${i}`}>Name</label>
                <input id={`nn${i}`} value={n.name} placeholder="Lakshmi aunty next door" onChange={(e) => setN(i, 'name', e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor={`np${i}`}>Phone number</label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input id={`np${i}`} type="tel" inputMode="tel" value={n.phone} placeholder="+91 98765 43210" onChange={(e) => setN(i, 'phone', e.target.value)} style={{ flex: 1 }} />
                  <button type="button" className="btn btn-text btn-sm" onClick={() => setNeighbours((ns) => ns.filter((_, j) => j !== i))}>Remove</button>
                </div>
              </div>
            </div>
          ))}
          {neighbours.length < 5 && (
            <button type="button" className="btn btn-quiet btn-sm" onClick={() => setNeighbours((ns) => [...ns, { name: '', phone: '' }])}>+ Add a neighbour or relative</button>
          )}
        </fieldset>
        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button>
          {msg && <span className="toast" role="status" style={{ margin: 0 }}>{msg}</span>}
          {err && <p className="error" role="alert">{err}</p>}
        </div>
      </form>
    </>
  )
}
