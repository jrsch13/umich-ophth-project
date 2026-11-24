import { useEffect, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'
import { stationPost } from '../stationApi'

function AuthCard({ title, children }) {
  return (
    <main className='page auth-page'>
      <section className='card auth-card'>
        <p className='eyebrow'>ERGONOMIC TRAINING STATION</p>
        <h1>{title}</h1>
        {children}
      </section>
    </main>
  )
}

export function LoginPage() {
  const { checking, user, logIn } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (checking) return <AuthCard title='Log In'><p role='status'>Checking sign-in…</p></AuthCard>
  if (user) {
    const destination = location.state?.from
    return <Navigate to={typeof destination === 'string' && /^\/(?![/\\])/.test(destination) ? destination : '/'} replace />
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await logIn(email.trim(), password)
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title='Log In'>
      <form onSubmit={submit}>
        <label className='field'><span>Email</span>
          <input type='email' autoComplete='username' required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label className='field'><span>Password</span>
          <input type='password' autoComplete='current-password' required maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className='posture-load-error' role='alert'>{error}</p>}
        <button className='button primary full' type='submit' disabled={busy}>{busy ? 'Logging in…' : 'Log In'}</button>
      </form>
    </AuthCard>
  )
}

export function AcceptInvitationPage() {
  const { user } = useAuth()
  const location = useLocation()
  const token = new URLSearchParams(location.hash.slice(1)).get('token')
  const [invitation, setInvitation] = useState(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) return undefined
    const controller = new AbortController()
    setInvitation(null)
    setError('')
    setAccepted(false)
    stationPost('/auth/invitations/preview', { token }, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setInvitation({ ...result, token }) })
      .catch((failure) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [token])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await stationPost('/auth/invitations/accept', { token, email: invitation.email, password })
      setAccepted(true)
      setPassword('')
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard title='Accept Invitation'>
      {!token && <p className='posture-load-error' role='alert'>This invitation link is incomplete.</p>}
      {token && !invitation && !error && <p role='status'>Checking invitation…</p>}
      {error && <p className='posture-load-error' role='alert'>{error}</p>}
      {accepted ? (
        <>
          <p role='status'>Your resident account is ready.</p>
          {user ? <Link to='/'>Return to the station to log out</Link> : <Link className='button primary' to='/login'>Log In</Link>}
        </>
      ) : invitation?.token === token && (
        <form onSubmit={submit}>
          <label className='field'><span>Confirm invited email</span>
            <input type='email' autoComplete='username' readOnly value={invitation.email} />
          </label>
          <label className='field'><span>Password (12–128 characters)</span>
            <input type='password' autoComplete='new-password' required minLength={12} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          <button className='button primary full' type='submit' disabled={busy}>{busy ? 'Creating account…' : 'Create Account'}</button>
        </form>
      )}
    </AuthCard>
  )
}
