import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth'

const tabs = [
  { to: '/', label: 'Home', end: true },
  { to: '/new', label: 'New Session' },
  { to: '/history', label: 'Session Analysis' },
  { to: '/cameras', label: 'Cameras' },
]

export default function AppShell({ children }) {
  const { user, logOut } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function signOut() {
    setBusy(true)
    setError('')
    try {
      await logOut()
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className='app'>
      <header className='topbar'>
        <div className='brand-wrap'>
          <div className='brand-mark'>E</div>
          <div><div className='brand'>Ergonomic Training Station</div><div className='brand-subtitle'>Ophthalmology posture feedback</div></div>
        </div>
        <div className='user-chip'>
          <div className='signed-in-user'>
            <div className='user-name' title={user.email}>{user.email}</div>
            <div className='user-meta'>{user.role === 'admin' ? 'Administrator' : 'Resident'}</div>
          </div>
          <button className='button secondary small' type='button' onClick={signOut} disabled={busy}>Log Out</button>
        </div>
      </header>
      <nav className='tabs'>
        {tabs.map(({ to, label, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>{label}</NavLink>
        ))}
      </nav>
      <main className='page'>
        {error && <p className='notice' role='alert'>{error}</p>}
        {children}
      </main>
      <footer className='footer'>Research prototype • Posture/exposure feedback, not a clinical risk score</footer>
    </div>
  )
}

