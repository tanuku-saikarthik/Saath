import { useState } from 'react'
import { api, DemoActionError, fmtDay, useApi, type Note, type Parent } from '../api'

/** Write a message Saath passes on in tonight's call, and see her reply to the last one. */
export function MessageCard({ parent, anchor }: { parent: Parent; anchor: Date }) {
  const notes = useApi<Note[]>(`/api/parents/${parent.id}/notes`)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const name = parent.address_term
  const pending = (notes.data ?? []).filter((n) => n.pending)
  const lastDelivered = (notes.data ?? []).find((n) => !n.pending)

  const send = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setMsg('')
    try {
      await api<Note>(`/api/parents/${parent.id}/notes`, { method: 'POST', body: JSON.stringify({ text }) })
      setText('')
      notes.reload()
    } catch (ex) {
      setMsg(ex instanceof DemoActionError ? ex.message : (ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const askNow = async () => {
    if (!text.trim()) return
    setBusy(true)
    setMsg('')
    try {
      const r = await api<{ call: { status: string; error?: string } }>(`/api/parents/${parent.id}/ask-now`, { method: 'POST', body: JSON.stringify({ text }) })
      setText('')
      setMsg(r.call.status === 'failed' ? `Couldn't place the call: ${r.call.error}` : `Calling ${name} now. Her answer will appear here a minute after the call ends.`)
      notes.reload()
    } catch (ex) {
      setMsg(ex instanceof DemoActionError ? ex.message : (ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    try {
      await api(`/api/notes/${id}`, { method: 'DELETE' })
      notes.reload()
    } catch (ex) {
      setMsg((ex as Error).message)
    }
  }

  return (
    <section className="msg" aria-labelledby="msg-h">
      <h2 className="h2" id="msg-h">Say something to {name}</h2>
      {lastDelivered && (
        <div className="msg-thread">
          <p className="msg-you"><span className="msg-who">{lastDelivered.is_question ? 'You asked' : 'You'}, {fmtDay(lastDelivered.delivered_at ?? lastDelivered.created_at, anchor)}</span>{lastDelivered.text}</p>
          {lastDelivered.reply ? (
            <p className="msg-her"><span className="msg-who">{name} replied</span>{lastDelivered.reply}</p>
          ) : (
            <p className="meta small">Saath passed it on. She didn't send anything back.</p>
          )}
        </div>
      )}
      {pending.map((n) => (
        <div className="msg-pending" key={n.id}>
          <p><span className="msg-who">Saath will pass this on tonight</span>{n.text}</p>
          <button className="btn btn-text btn-sm" onClick={() => remove(n.id)}>Remove</button>
        </div>
      ))}
      <form onSubmit={send} className="msg-form">
        <label htmlFor="msg-text" className="sr-only">Message for {name}</label>
        <textarea
          id="msg-text"
          rows={2}
          maxLength={300}
          value={text}
          placeholder={`Type in English or ${parent.language === 'hi' ? 'Hindi' : 'Telugu'}. e.g. Did you eat lunch, ${name}?`}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="msg-actions">
          <span className="meta small">Saath says it in {parent.language === 'hi' ? 'Hindi' : 'Telugu'} and brings back her reply.</span>
          <button className="btn btn-quiet btn-sm" type="submit" disabled={busy || !text.trim()}>{busy ? 'Working…' : 'Send with tonight’s call'}</button>
          <button className="btn btn-primary btn-sm" type="button" onClick={askNow} disabled={busy || !text.trim()}>Ask her now</button>
        </div>
      </form>
      {msg && <p className="toast" role="status">{msg}</p>}
    </section>
  )
}
