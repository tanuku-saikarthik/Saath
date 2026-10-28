import type { Medicine } from '../api'
import { IconPlus, IconTrash } from './Icons'

export type ParentDraft = {
  name: string
  address_term: string
  phone: string
  language: 'te' | 'hi'
  call_time: string
  topics: string
  medicines: Medicine[]
}

type Props = { d: ParentDraft; set: (d: ParentDraft) => void }

export function AboutFields({ d, set }: Props) {
  return (
    <>
      <div className="grid2">
        <div className="field">
          <label htmlFor="pname">Her name</label>
          <input id="pname" value={d.name} onChange={(e) => set({ ...d, name: e.target.value })} required autoComplete="off" />
        </div>
        <div className="field">
          <label htmlFor="pterm">What you call her</label>
          <input id="pterm" value={d.address_term} placeholder="Amma, Nanna, Maa" onChange={(e) => set({ ...d, address_term: e.target.value })} required />
          <span className="hint">Saath greets her with this.</span>
        </div>
      </div>
      <div className="field">
        <label htmlFor="pphone">Her phone number</label>
        <input id="pphone" type="tel" inputMode="tel" value={d.phone} placeholder="+91 98765 43210" onChange={(e) => set({ ...d, phone: e.target.value })} required />
        <span className="hint">A normal phone works. No app or smartphone needed.</span>
      </div>
      <div className="field">
        <span id="plang" style={{ fontWeight: 500, fontSize: 14, color: 'var(--ink-2)' }}>Language for the calls</span>
        <div className="radio-row" role="radiogroup" aria-labelledby="plang">
          <label><input type="radio" name="lang" checked={d.language === 'te'} onChange={() => set({ ...d, language: 'te' })} /> Telugu</label>
          <label><input type="radio" name="lang" checked={d.language === 'hi'} onChange={() => set({ ...d, language: 'hi' })} /> Hindi</label>
        </div>
      </div>
    </>
  )
}

export function MedicineFields({ d, set }: Props) {
  const update = (i: number, m: Partial<Medicine>) => set({ ...d, medicines: d.medicines.map((x, j) => (j === i ? { ...x, ...m } : x)) })
  return (
    <>
      <div className="field">
        <span style={{ fontWeight: 500, fontSize: 14, color: 'var(--ink-2)' }}>Medicines Saath should ask about</span>
        {d.medicines.length > 0 && (
          <div className="med-row med-head" aria-hidden="true"><span>Name</span><span>When she takes it</span><span>Reminder call</span><span /></div>
        )}
        <div style={{ display: 'grid', gap: 8 }}>
          {d.medicines.map((m, i) => (
            <div className="med-row" key={i}>
              <input aria-label={`Medicine ${i + 1} name`} value={m.name} placeholder="BP tablet" onChange={(e) => update(i, { name: e.target.value })} />
              <input aria-label={`Medicine ${i + 1} timing`} value={m.timing} placeholder="Morning" onChange={(e) => update(i, { timing: e.target.value })} />
              <input aria-label={`Reminder call time for medicine ${i + 1} (optional)`} type="time" value={m.reminder_time ?? ''} onChange={(e) => update(i, { reminder_time: e.target.value })} />
              <button type="button" className="icon-btn" aria-label={`Remove ${m.name || 'medicine'}`} onClick={() => set({ ...d, medicines: d.medicines.filter((_, j) => j !== i) })}>
                <IconTrash />
              </button>
            </div>
          ))}
        </div>
        <div>
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => set({ ...d, medicines: [...d.medicines, { name: '', timing: '' }] })}>
            <IconPlus /> Add a medicine
          </button>
        </div>
        <span className="hint">Give a medicine a reminder time and Saath places a short call then to remind her and check she took it. Leave it empty for no reminder.</span>
      </div>
      <div className="field">
        <label htmlFor="ptopics">Things she loves to talk about</label>
        <input id="ptopics" value={d.topics} placeholder="Her garden, temple visits, grandson Arjun" onChange={(e) => set({ ...d, topics: e.target.value })} />
        <span className="hint">Separate with commas. Saath brings these up to keep the chat warm.</span>
      </div>
    </>
  )
}

export function TimeField({ d, set }: Props) {
  return (
    <div className="field" style={{ maxWidth: 260 }}>
      <label htmlFor="ptime">Call her every evening at</label>
      <input id="ptime" type="time" value={d.call_time} onChange={(e) => set({ ...d, call_time: e.target.value })} required />
      <span className="hint">India time. If she doesn't answer, Saath tries once more 30 minutes later.</span>
    </div>
  )
}

export const toPayload = (d: ParentDraft) => ({
  name: d.name.trim(),
  address_term: d.address_term.trim(),
  phone: d.phone.replace(/\s+/g, ''),
  language: d.language,
  call_time: d.call_time,
  topics: d.topics.split(',').map((t) => t.trim()).filter(Boolean),
})
export const medsPayload = (d: ParentDraft) =>
  d.medicines.filter((m) => m.name.trim()).map((m) => ({ name: m.name.trim(), timing: m.timing.trim(), reminder_time: m.reminder_time ?? '' }))
