import { createContext, useContext, useEffect, useState } from 'react'
import { HashRouter, Link, MemoryRouter, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api, authStatus, detectMode, openSeededDemo, type Parent, seededForced } from './api'
import { BrandMark, IconBell, IconCalls, IconHome, IconUser, IconWeek } from './components/Icons'
import { Loading } from './components/Pieces'
import Today from './pages/Today'
import CallDetail from './pages/CallDetail'
import Calls from './pages/Calls'
import Alerts from './pages/Alerts'
import Profile from './pages/Profile'
import Setup from './pages/Setup'
import TestCall from './pages/TestCall'
import { Login } from './components/Login'
import Week from './pages/Week'

type Ctx = { parent: Parent; demo: boolean; refreshParent: () => void; unseen: number; setUnseen: (n: number) => void }
const ParentCtx = createContext<Ctx | null>(null)
export const useParent = () => {
  const c = useContext(ParentCtx)
  if (!c) throw new Error('useParent outside provider')
  return c
}

/** Top-right menu in the demo: shows "Demo"; opening it reveals the Setup button. */
function DemoMenu() {
  const [open, setOpen] = useState(false)
  return (
    <div className="demo-menu">
      <button type="button" className="demo-menu-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Demo <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="demo-menu-pop" role="menu">
          <button type="button" role="menuitem" className="btn btn-primary btn-sm" onClick={() => { setOpen(false); window.dispatchEvent(new Event('saath-signin')) }}>Setup</button>
        </div>
      )}
    </div>
  )
}

function Shell({ children, parent, unseen, demo }: { children: React.ReactNode; parent: Parent | null; unseen: number; demo: boolean }) {
  const nav = [
    { to: '/', label: 'Today', icon: <IconHome /> },
    { to: '/week', label: 'Week', icon: <IconWeek /> },
    { to: '/calls', label: 'Calls', icon: <IconCalls /> },
    { to: '/alerts', label: 'Alerts', icon: <IconBell /> },
    { to: '/profile', label: parent ? parent.address_term : 'Profile', icon: <IconUser /> },
  ]
  return (
    <div className="shell">
      <header className="topbar">
       <div className="topbar-inner">
        <Link to="/" className="brand" aria-label="Saath home">
          <BrandMark className="brand-mark" />
          <span className="brand-word">Saath</span>
        </Link>
        {parent && (
          <nav className="topnav" aria-label="Main">
            {nav.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
                <span className="nav-ico" aria-hidden="true">{n.icon}</span>
                {n.label}
                {n.to === '/alerts' && unseen > 0 && <span className="badge-dot" style={{ marginLeft: 6 }}>{unseen}</span>}
              </NavLink>
            ))}
          </nav>
        )}
        {demo && <DemoMenu />}
       </div>
      </header>
      {children}
      {parent && (
        <nav className="tabbar" aria-label="Main">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              <span style={{ position: 'relative' }}>
                {n.icon}
                {n.to === '/alerts' && unseen > 0 && <span className="badge-dot" style={{ position: 'absolute', top: -6, right: -12 }}>{unseen}</span>}
              </span>
              {n.label}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  )
}

function ScrollTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

function Page({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  return <div key={pathname} className="page">{children}</div>
}

function Gate() {
  const [st, setSt] = useState<'checking' | 'login' | 'ok'>('checking')
  // Visitors without the family password land in the demo; Setup (top right) asks for the password.
  const check = () => {
    if (seededForced()) return setSt('ok')
    authStatus()
      .then((a) => {
        if (a.required && !a.authed) openSeededDemo()
        setSt('ok')
      })
      .catch(() => setSt('ok')) // no backend: demo preview
  }
  useEffect(() => {
    check()
    const f = () => setSt('login')
    window.addEventListener('saath-signin', f)
    return () => window.removeEventListener('saath-signin', f)
  }, [])
  if (st === 'checking') return <Loading />
  if (st === 'login') return <Login onDone={() => { window.location.reload() }} />
  return <Root />
}

function Root() {
  const [parent, setParent] = useState<Parent | null>(null)
  const [demo, setDemo] = useState(false)
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [error, setError] = useState('')
  const [unseen, setUnseen] = useState(0)

  const load = () => {
    detectMode().then((m) => setDemo(m === 'demo'))
    api<Parent[]>('/api/parents')
      .then((ps) => {
        if (ps.length) {
          setParent(ps[0])
          setState('ready')
        } else setState('empty')
      })
      .catch((e: Error) => {
        setError(e.message)
        setState('error')
      })
  }
  useEffect(load, [])

  useEffect(() => {
    if (parent) api<{ seen: boolean }[]>(`/api/parents/${parent.id}/alerts`).then((as) => setUnseen(as.filter((a) => !a.seen).length)).catch(() => {})
  }, [parent])

  return (
    <Shell parent={parent} unseen={unseen} demo={demo}>
      {demo && (
        <div className="demo-note">
          <span>Sample data. Calls and changes are off in this view.</span>
        </div>
      )}
      <main className="main" id="main">
        {state === 'loading' && <Loading />}
        {state === 'error' && <p className="empty" role="alert">Couldn't reach Saath: {error}</p>}
        {state === 'empty' && (
          <Routes>
            <Route path="*" element={<Setup onDone={load} />} />
          </Routes>
        )}
        {state === 'ready' && parent && (
          <ParentCtx.Provider value={{ parent, demo, refreshParent: load, unseen, setUnseen }}>
            <Page>
            <Routes>
              <Route path="/" element={<Today />} />
              <Route path="/calls" element={<Calls />} />
              <Route path="/calls/:id" element={<CallDetail />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/setup" element={<Setup onDone={load} />} />
              <Route path="/talk" element={<TestCall />} />
              <Route path="/test-call" element={<Navigate to="/talk" replace />} />
              <Route path="/week" element={<Week />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </Page>
          </ParentCtx.Provider>
        )}
      </main>
    </Shell>
  )
}

// The shareable single-file preview keeps routes in memory (its host only passes plain #names).
const Router = import.meta.env.MODE === 'single' ? MemoryRouter : HashRouter

export default function App() {
  return (
    <Router>
      <ScrollTop />
      <Gate />
    </Router>
  )
}
