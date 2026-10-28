import { useState } from 'react'
import { api, DemoActionError, useApi, type Parent } from '../api'

type Status = { paired: boolean; devices: { id: number; paired_at: string | null; last_seen: string | null; last_fine: string | null; last_sos: string | null }[] }
type Code = { code: string; expires_in_minutes: number; link: string }

/** Pair her smartphone with the 'Saath for her' page: SOS, call you, talk to Saath, "I'm fine". */
export function HerPhoneCard({ parent }: { parent: Parent }) {
  const status = useApi<Status>(`/api/parents/${parent.id}/her-phone`)
  const [code, setCode] = useState<Code | null>(null)
  const [msg, setMsg] = useState('')
  const name = parent.address_term

  const make = async () => {
    setMsg('')
    try {
      setCode(await api<Code>(`/api/parents/${parent.id}/pair-code`, { method: 'POST' }))
    } catch (e) {
      setMsg(e instanceof DemoActionError ? e.message : (e as Error).message)
    }
  }
  const unpair = async () => {
    try {
      await api(`/api/parents/${parent.id}/her-phone`, { method: 'DELETE' })
      setCode(null)
      status.reload()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }
  const dev = status.data?.devices?.[0]

  return (
    <fieldset className="fieldset">
      <legend>{name}'s phone</legend>
      <p className="hint" style={{ margin: '0 0 10px' }}>
        If {name} has a smartphone, she can open a simple page with four big buttons: SOS (press and hold), call you, talk to Saath, and “I'm fine today”. SOS alerts you and rings your emergency contacts. Her daily Saath call stays a normal phone call.
      </p>
      {status.data?.paired && dev ? (
        <div className="sos-box">
          <p style={{ margin: 0, fontWeight: 500 }}>{name}'s phone is paired</p>
          <p className="small" style={{ margin: '4px 0 8px', color: 'var(--ink-2)' }}>
            Last opened: {dev.last_seen ?? 'not yet'}{dev.last_fine ? ` · Last “I'm fine”: ${dev.last_fine}` : ''}{dev.last_sos ? ` · Last SOS: ${dev.last_sos}` : ''}
          </p>
          <button type="button" className="btn btn-text btn-sm" onClick={unpair}>Unpair this phone</button>
        </div>
      ) : code ? (
        <div className="sos-box">
          <p className="meta small" style={{ margin: 0 }}>On {name}'s phone, open this link and enter the code</p>
          <p className="small" style={{ margin: '4px 0', wordBreak: 'break-all' }}>{code.link}</p>
          <p className="sos-num" style={{ margin: '2px 0 6px', letterSpacing: 6 }}>{code.code}</p>
          <p className="meta small" style={{ margin: 0 }}>Works once, for {code.expires_in_minutes} minutes. Then tap “Add to home screen”.</p>
        </div>
      ) : (
        <button type="button" className="btn btn-quiet btn-sm" onClick={make}>Set up {name}'s phone</button>
      )}
      {msg && <p className="toast" role="status">{msg}</p>}
    </fieldset>
  )
}
