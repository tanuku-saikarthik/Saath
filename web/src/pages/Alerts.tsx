import { anchorDate, useApi, type Alert } from '../api'
import { useParent } from '../App'
import { AlertCard, ErrorNote, Loading } from '../components/Pieces'

export default function Alerts() {
  const { parent, setUnseen } = useParent()
  const { data, error, loading, reload } = useApi<Alert[]>(`/api/parents/${parent.id}/alerts`)
  if (loading && !data) return <Loading />
  if (error) return <ErrorNote message={error} />
  const alerts = data ?? []
  const anchor = anchorDate()
  const unread = alerts.filter((a) => !a.seen)
  const read = alerts.filter((a) => a.seen)
  const onSeen = () => {
    reload()
    setUnseen(Math.max(0, unread.length - 1))
  }

  return (
    <div className="alerts-page">
      <div className="page-head">
        <h1 className="page-title">Alerts</h1>
      </div>
      <p className="muted" style={{ marginTop: -6, marginBottom: 20 }}>
        Saath alerts you when {parent.address_term} mentions something urgent, calls Saath herself, misses a check-in, or her mood or voice stays away from her usual for several calls. One bad day never sends an alert on its own.
      </p>
      {alerts.length === 0 && <p className="empty">No alerts yet.</p>}
      <div className="alert-grid">
        {unread.map((a) => <AlertCard key={a.id} alert={a} parent={parent} anchor={anchor} onSeen={onSeen} />)}
      </div>
      {read.length > 0 && (
        <>
          <h2 className="h2" style={{ marginTop: 28 }}>Read</h2>
          <div className="alert-grid">
            {read.map((a) => <AlertCard key={a.id} alert={a} parent={parent} anchor={anchor} />)}
          </div>
        </>
      )}
    </div>
  )
}
