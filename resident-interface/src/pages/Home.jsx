import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import StatusPill from '../components/StatusPill'
import SectionHeader from '../components/SectionHeader'
import InviteUsers from '../components/InviteUsers'
import { useAuth } from '../auth'
import { stationRequest } from '../stationApi'

function MostRecentSession() {
  const [session, setSession] = useState(undefined)
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller

    async function loadSession() {
      try {
        const { sessions = [] } = await stationRequest('/sessions', { signal })
        if (signal.aborted) return
        // The station lists sessions from most recent to oldest.
        for (const entry of sessions) {
          if (entry.analysis_status !== 'complete') continue
          const detail = await stationRequest(`/sessions/${encodeURIComponent(entry.session_id)}`, { signal })
          if (signal.aborted) return
          if (detail.analysis_status?.status === 'complete') {
            setSession(detail)
            return
          }
        }
        setSession(null)
      } catch {
        if (!signal.aborted) setError(true)
      }
    }

    loadSession()
    return () => controller.abort()
  }, [])

  const metrics = session?.posture_summaries || []
  const statusMessage = error
    ? 'Could not load the most recent analyzed session.'
    : session === undefined
      ? 'Loading session results…'
      : !session ? 'No completed analyses yet.' : ''

  return (
    <section className='card'>
      <SectionHeader title='Most recent session' description={session ? 'Analyzed time within the reference zone' : undefined} />
      {statusMessage && <p className='muted small' role={error ? 'alert' : 'status'}>{statusMessage}</p>}
      {session && (
        <>
          {metrics.length ? (
            <div className='metric-grid'>
              {metrics.map((metric) => {
                const percent = metric.reference_zone_exposure?.within_percent
                return (
                  <div className='metric' key={metric.metric}>
                    {Number.isFinite(percent) ? <strong>{percent}%</strong> : <strong className='metric-unavailable'>Unavailable</strong>}
                    <span className='metric-name'>{metric.label}</span>
                  </div>
                )
              })}
            </div>
          ) : <p className='muted small'>Posture results are unavailable for this session.</p>}
          <p className='small'>
            <Link to={`/history/${encodeURIComponent(session.session_id)}`}>
              {session.metadata?.session_label || session.session_id}
            </Link>
          </p>
        </>
      )}
    </section>
  )
}

export default function Home() {
  const { user } = useAuth()
  return (
    <>
      <section className='hero'>
        <div>
          <span className='eyebrow'>TRAINING STATION</span>
          <h1>Welcome back</h1>
          <p>Start a new ergonomic training session, review prior feedback, or check that the station cameras are ready.</p>
        </div>
        <Link className='button primary large' to='/new'>Start new session</Link>
      </section>
      <div className='grid two'>
        <section className='card'>
          <SectionHeader title='Station status' description='Current station readiness' />
          <div className='status-row'><span>Side camera</span><StatusPill tone='success'>Ready</StatusPill></div>
          <div className='status-row'><span>Rear camera</span><StatusPill tone='success'>Ready</StatusPill></div>
        </section>
        <MostRecentSession />
      </div>
      {user.role === 'admin' && <InviteUsers />}
      <section className='card'>
        <SectionHeader title='How a session works' />
        <div className='steps'>
          {[
            ['1', 'Start', 'Confirm cameras and begin the countdown.'],
            ['2', 'Reference', 'Hold a short neutral posture for calibration.'],
            ['3', 'Practice', 'Perform normal ophthalmology training.'],
            ['4', 'Review', 'See posture events and session feedback.'],
          ].map(([number, title, description]) => (
            <div className='step' key={number}>
              <span>{number}</span>
              <div><strong>{title}</strong><p>{description}</p></div>
            </div>
          ))}
        </div>
      </section>
    </>
  )
}
