import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import SectionHeader from '../components/SectionHeader'
import StatusPill from '../components/StatusPill'
import { stationPlotUrl, stationRequest } from '../stationApi'

const POLL_INTERVAL_MS = 3000

const plotTitles = {
  trunk_flexion_extension: 'Trunk Flexion / Extension',
  neck_flexion_extension: 'Neck Flexion / Extension',
  trunk_lateral_lean: 'Trunk Lateral Lean',
  shoulder_hiking: 'Shoulder Hiking',
  torso_confidence: 'Torso Keypoint Confidence',
}

const metricTitles = {
  Trunk_Flexion_Extension: 'Trunk Flexion / Extension',
  Neck_Flexion_Extension: 'Neck Flexion / Extension',
  Trunk_Lean: 'Trunk Lateral Lean',
  Right_Shoulder_Hiking_Dist: 'Right Shoulder Hiking',
  Left_Shoulder_Hiking_Dist: 'Left Shoulder Hiking',
}

const plotOrder = {
  side: ['trunk_flexion_extension', 'neck_flexion_extension', 'torso_confidence'],
  rear: ['trunk_lateral_lean', 'shoulder_hiking', 'torso_confidence'],
}

function formatDate(value) {
  if (!value) return 'Date unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function formatListDate(value) {
  if (!value) return 'Date unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
}

function statusDisplay(status, stage) {
  if (status === 'complete') return { label: 'Complete', tone: 'success', message: 'Posture analysis complete.' }
  if (status === 'failed') return { label: 'Analysis needs attention', tone: 'warning', message: 'Analysis needs attention.' }
  if (stage === 'openpose') return { label: 'Processing', tone: 'warning', message: 'Processing pose keypoints…' }
  if (stage === 'posture_analysis') return { label: 'Processing', tone: 'warning', message: 'Generating posture metrics…' }
  return { label: 'Processing', tone: 'warning', message: 'Waiting for analysis…' }
}

function viewName(view) {
  return view === 'side' ? 'Side' : view === 'rear' ? 'Rear' : view
}

function stageLabel(status) {
  if (status === 'complete') return 'Complete'
  if (status === 'failed') return 'Needs attention'
  if (status === 'processing') return 'Processing'
  return 'Pending'
}

function PlotCard({ plot }) {
  const [unavailable, setUnavailable] = useState(false)
  const url = stationPlotUrl(plot.url)
  const key = plot.name.replace(/\.png$/i, '')
  const title = plotTitles[key] || key.replaceAll('_', ' ')

  return (
    <article className='card analysis-plot-card'>
      <h4>{title}</h4>
      {url && !unavailable ? (
        <a href={url} target='_blank' rel='noopener noreferrer' aria-label={`View ${title} larger`}>
          <img src={url} alt={`${title} posture analysis plot`} onError={() => setUnavailable(true)} />
        </a>
      ) : (
        <p className='muted'>This plot is currently unavailable.</p>
      )}
      {url && !unavailable ? <p className='muted small'>Select the graph to view it larger.</p> : null}
    </article>
  )
}

function Summary({ summary }) {
  if (!summary) return null
  const metrics = Object.entries(summary.metrics || {})
  return (
    <section className='analysis-summary'>
      <h4>Posture analysis summary</h4>
      <div className='analysis-summary-facts'>
        {Number.isFinite(summary.total_json_frames) ? <span><strong>{summary.total_json_frames.toLocaleString()}</strong> analyzed frames</span> : null}
        {Number.isFinite(summary.neutral_seconds) ? <span><strong>{summary.neutral_seconds}</strong> neutral baseline seconds</span> : null}
      </div>
      {metrics.length ? (
        <div className='analysis-metric-grid'>
          {metrics.map(([name, metric]) => (
            <div className='analysis-metric' key={name}>
              <strong>{metricTitles[name] || name.replaceAll('_', ' ')}</strong>
              {Number.isFinite(metric?.pct_valid_frames_over_threshold) ? (
                <span>{metric.pct_valid_frames_over_threshold.toFixed(1)}% of valid frames exceeding threshold</span>
              ) : <span>Threshold exposure unavailable</span>}
              {Number.isFinite(metric?.valid_frames) ? <small>{metric.valid_frames.toLocaleString()} valid frames</small> : null}
            </div>
          ))}
        </div>
      ) : null}
      <p className='muted small'>Research thresholds for posture exposure review.</p>
    </section>
  )
}

function SessionList({ sessions }) {
  const navigate = useNavigate()

  if (!sessions.length) {
    return <div className='card analysis-empty'>
      <h3>No sessions available for analysis yet.</h3>
      <p className='muted'>Complete a New Session to see posture results here.</p>
      <Link className='button primary' to='/new'>New Session</Link>
    </div>
  }

  return <div className='card table-card analysis-table-card'>
    <table className='analysis-table'>
      <thead>
        <tr>
          <th scope='col'>Session Label</th>
          <th scope='col'>Date</th>
          <th scope='col'>Status</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map((session) => {
          const label = session.session_label || session.session_id
          const state = statusDisplay(session.analysis_status)
          const destination = `/history/${encodeURIComponent(session.session_id)}`
          const openSession = () => navigate(destination)
          return <tr
            className='analysis-session-row'
            key={session.session_id}
            tabIndex={0}
            role='link'
            aria-label={`Open analysis for ${label}`}
            onClick={openSession}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                openSession()
              }
            }}
          >
            <td className='analysis-session-label'>{label}</td>
            <td className='analysis-session-date'>{formatListDate(session.recorded_at)}</td>
            <td className='analysis-session-status'><StatusPill tone={state.tone}>{state.label}</StatusPill></td>
          </tr>
        })}
      </tbody>
    </table>
  </div>
}

function SessionDetail({ detail, status, recordedAt, retryingView, onRetry }) {
  const metadata = detail.metadata || {}
  const overall = statusDisplay(status?.status, status?.stage)
  const views = detail.available_views || []

  return <>
    <Link className='analysis-back' to='/history'>← All sessions</Link>
    <section className='card analysis-detail-header'>
      <div>
        <p className='eyebrow'>SESSION ANALYSIS</p>
        <h3>{metadata.session_label || detail.session_id}</h3>
        <p className='muted'>{formatDate(metadata.started_at || metadata.ended_at || metadata.created_at || recordedAt)}</p>
        {metadata.resident_or_study_id ? <p className='muted small'>Resident / Study ID: {metadata.resident_or_study_id}</p> : null}
      </div>
      <div className='analysis-overall-status'>
        <StatusPill tone={overall.tone}>{overall.label}</StatusPill>
        <p className='muted'>{overall.message}</p>
      </div>
    </section>
    {views.length ? views.map((view) => {
      const viewData = detail.views?.[view] || {}
      const viewStatus = status?.views?.[view] || viewData.analysis_status || {}
      const plots = (viewData.plots || []).filter((plot) => stationPlotUrl(plot.url)).sort((a, b) => {
        const order = plotOrder[view] || []
        const first = order.indexOf(a.name.replace(/\.png$/i, ''))
        const second = order.indexOf(b.name.replace(/\.png$/i, ''))
        return (first < 0 ? order.length : first) - (second < 0 ? order.length : second)
      })
      const canRetry = viewStatus.openpose_status === 'complete'
        && ['failed', 'pending'].includes(viewStatus.posture_status)
        && status?.status !== 'processing'
      return <section className='analysis-view' key={view}>
        <div className='analysis-view-header'>
          <div>
            <h3>{viewName(view)} view</h3>
            <p className='muted small'>
              Pose keypoints: {stageLabel(viewStatus.openpose_status)} · Posture analysis: {stageLabel(viewStatus.posture_status)}
            </p>
          </div>
          {canRetry ? <button className='button secondary' type='button' onClick={() => onRetry(view)} disabled={retryingView === view}>
            {retryingView === view ? 'Starting…' : 'Retry Analysis'}
          </button> : null}
        </div>
        {plots.length ? <div className='analysis-plot-grid'>{plots.map((plot) => <PlotCard key={plot.name} plot={plot} />)}</div>
          : <div className='card'><p className='muted'>Plots will appear here when posture analysis finishes.</p></div>}
        <Summary summary={viewData.summary} />
      </section>
    }) : <div className='card'><p className='muted'>No Side or Rear view is available for this session.</p></div>}
  </>
}

export default function SessionAnalysis() {
  const { sessionId } = useParams()
  const [sessions, setSessions] = useState([])
  const [detail, setDetail] = useState(null)
  const [status, setStatus] = useState(null)
  const [recordedAt, setRecordedAt] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [retryingView, setRetryingView] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    setError('')
    if (sessionId) {
      Promise.all([
        stationRequest(`/sessions/${encodeURIComponent(sessionId)}`, { signal: controller.signal }),
        stationRequest('/sessions', { signal: controller.signal }).catch(() => ({ sessions: [] })),
      ])
        .then(([result, listing]) => {
          if (controller.signal.aborted) return
          setDetail(result)
          setStatus(result.analysis_status)
          setRecordedAt(listing.sessions?.find((item) => item.session_id === sessionId)?.recorded_at || null)
        })
        .catch(() => { if (!controller.signal.aborted) setError('Could not load this session. Check the station service and try again.') })
        .finally(() => { if (!controller.signal.aborted) setIsLoading(false) })
    } else {
      setDetail(null)
      setStatus(null)
      setRecordedAt(null)
      stationRequest('/sessions', { signal: controller.signal })
        .then((result) => { if (!controller.signal.aborted) setSessions(Array.isArray(result.sessions) ? result.sessions : []) })
        .catch(() => { if (!controller.signal.aborted) setError('Could not load sessions. Check the station service and try again.') })
        .finally(() => { if (!controller.signal.aborted) setIsLoading(false) })
    }
    return () => controller.abort()
  }, [sessionId])

  useEffect(() => {
    if (!sessionId || !status || ['complete', 'failed'].includes(status.status)) return undefined
    let active = true
    let inFlight = false
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const latest = await stationRequest(`/sessions/${encodeURIComponent(sessionId)}/analysis-status`)
        if (!active) return
        setStatus(latest)
        if (['complete', 'failed'].includes(latest.status)) {
          const updated = await stationRequest(`/sessions/${encodeURIComponent(sessionId)}`)
          if (active) setDetail(updated)
        }
      } catch {
        if (active) setError('Analysis status could not be refreshed. Try reloading this page.')
      } finally {
        inFlight = false
      }
    }
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS)
    return () => { active = false; window.clearInterval(timer) }
  }, [sessionId, status?.status])

  const retry = async (view) => {
    setRetryingView(view)
    setError('')
    try {
      const started = await stationRequest(`/sessions/${encodeURIComponent(sessionId)}/analysis/${view}/retry`, { method: 'POST' })
      setStatus(started)
      if (['complete', 'failed'].includes(started.status)) {
        const updated = await stationRequest(`/sessions/${encodeURIComponent(sessionId)}`)
        setDetail(updated)
      }
    } catch {
      setError('Could not start posture analysis. Check that pose keypoints are available and try again.')
    } finally {
      setRetryingView(null)
    }
  }

  return <>
    <SectionHeader title='Session Analysis' description='Review posture analysis from previous sessions.' />
    {error ? <div className='notice analysis-error' role='alert'>{error}</div> : null}
    {isLoading ? <div className='card'><p className='muted'>Loading session analysis…</p></div>
      : sessionId ? (detail ? <SessionDetail detail={detail} status={status || detail.analysis_status} recordedAt={recordedAt} retryingView={retryingView} onRetry={retry} /> : null)
        : <SessionList sessions={sessions} />}
  </>
}
