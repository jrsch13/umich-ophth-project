import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import SectionHeader from '../components/SectionHeader'
import StatusPill from '../components/StatusPill'
import { STATION_SERVICE_URL, stationRequest } from '../stationApi'

const POLL_INTERVAL_MS = 3000

const POSTURE_METRICS = [
  {
    key: 'neck_flexion_extension',
    label: 'Neck flexion / extension',
    view: 'side',
    explanation: 'Neck flexion/extension describes the head and neck moving forward or backward away from a neutral alignment. Sustained non-neutral neck positions can increase muscular loading. Ergonomic guidance for ophthalmic work recommends adjusting the patient and equipment so the neck can remain close to neutral.',
    reference: 'RULA groups increasing neck flexion into approximately 0–10°, 10–20°, and >20° categories and separately flags neck extension.',
  },
  {
    key: 'shoulder_hiking',
    label: 'Shoulder hiking',
    view: 'rear',
    explanation: 'Shoulder hiking is elevation of one or both shoulders away from a relaxed resting position. Ergonomic guidance recommends keeping the shoulders relaxed and avoiding sustained elevation while working.',
    reference: 'RULA treats a raised shoulder as an additional postural loading factor; it does not define a universal percentage threshold.',
  },
  {
    key: 'forward_trunk_lean',
    label: 'Forward trunk lean',
    view: 'side',
    explanation: 'Forward trunk lean is flexion of the torso away from an upright or neutral posture. In ophthalmology this commonly occurs when the clinician leans toward a slit lamp or patient rather than bringing the equipment and patient closer.',
    reference: 'Ergonomic screening methods such as RULA increase posture scores with increasing trunk flexion.',
  },
  {
    key: 'lateral_trunk_lean',
    label: 'Lateral trunk lean',
    view: 'rear',
    explanation: 'Lateral trunk lean is side-bending of the torso away from its neutral vertical alignment. Repeated or sustained side-bending is considered an awkward posture; positioning the patient and equipment to avoid reaching or leaning to one side can reduce this exposure.',
    reference: null,
  },
]

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

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return 'Time unavailable'
  const tenths = Math.round(seconds * 10)
  const minutes = Math.floor(tenths / 600)
  const remainder = ((tenths % 600) / 10).toFixed(1).padStart(4, '0')
  return `${minutes}:${remainder}`
}

function formatMetricValue(value, unit) {
  if (!Number.isFinite(value)) return 'Unavailable'
  if (unit === 'degrees') return `${value.toFixed(2)}°`
  if (unit === 'trunk_length_ratio') return `${value.toFixed(4)} trunk-length ratio`
  return `${value.toFixed(2)} ${unit}`
}

function formatThreshold(value, unit) {
  if (!Number.isFinite(value)) return 'Unavailable'
  if (unit === 'degrees') return `${value}°`
  if (unit === 'trunk_length_ratio') return `${value} trunk-length ratio`
  return `${value} ${unit}`
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

function metricCanLoad(summary) {
  return summary?.status === 'available'
    || (summary?.status === 'insufficient_tracking' && summary.reason === 'no_valid_tracking')
}

function viewIsProcessing(viewStatus, overallStatus) {
  const stages = [viewStatus?.openpose_status, viewStatus?.posture_status]
  return stages.some((stage) => stage === 'pending' || stage === 'processing')
    || (overallStatus === 'processing' && stages.every((stage) => !['complete', 'failed'].includes(stage)))
}

function viewIsFailed(viewStatus) {
  return viewStatus?.openpose_status === 'failed' || viewStatus?.posture_status === 'failed'
}

function PostureSummaryCard({
  definition,
  summary,
  viewStatus,
  overallStatus,
  selected,
  onSelect,
}) {
  const canLoad = metricCanLoad(summary)
  const isPending = !canLoad && viewIsProcessing(viewStatus, overallStatus)
  const isFailed = !canLoad && viewIsFailed(viewStatus)
  const notRecorded = summary?.reason === 'view_not_recorded'
  const insufficient = summary?.status === 'insufficient_tracking'
    && summary.reason === 'no_valid_tracking'
  const unavailableText = notRecorded
    ? 'View not recorded'
    : isPending
      ? 'Analysis processing'
      : isFailed
        ? 'Analysis needs attention'
        : insufficient
          ? 'Insufficient tracking'
          : 'Analysis data unavailable'
  const hasExposure = summary?.status === 'available'
    && Number.isFinite(summary.within_threshold_percent)
    && Number.isFinite(summary.above_threshold_percent)

  return (
    <button
      className={`card posture-summary-card${selected ? ' selected' : ''}${canLoad ? '' : ' unavailable'}`}
      type='button'
      disabled={!canLoad}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <div className='posture-donut'>
        {hasExposure ? (
          <div
            role='img'
            aria-label={`${definition.label}: ${summary.within_threshold_percent}% within threshold, ${summary.above_threshold_percent}% above threshold`}
          >
            <PieChart width={100} height={100} aria-hidden='true'>
              <Pie
                data={[
                  { name: 'Within threshold', value: summary.within_threshold_percent },
                  { name: 'Above threshold', value: summary.above_threshold_percent },
                ]}
                dataKey='value'
                nameKey='name'
                innerRadius={30}
                outerRadius={45}
                stroke='#fff'
                strokeWidth={2}
                isAnimationActive={false}
              >
                <Cell fill='#43885c' />
                <Cell fill='#d89a3b' />
              </Pie>
            </PieChart>
          </div>
        ) : (
          <div className='posture-donut-empty' aria-hidden='true'>—</div>
        )}
      </div>
      <div className='posture-card-content'>
        <h3>{definition.label}</h3>
        <p>{definition.explanation}</p>
        {definition.reference ? <p className='posture-reference'>{definition.reference}</p> : null}
        <p className='posture-threshold'>
          Threshold: {formatThreshold(summary?.threshold, summary?.unit || (definition.view === 'side' ? 'degrees' : 'trunk_length_ratio'))}
        </p>
        {hasExposure ? (
          <>
            <div className='posture-exposure-legend'>
              <span><i className='legend-swatch within' />Within threshold <strong>{summary.within_threshold_percent.toFixed(1)}%</strong></span>
              <span><i className='legend-swatch above' />Above threshold <strong>{summary.above_threshold_percent.toFixed(1)}%</strong></span>
            </div>
          </>
        ) : (
          <span className={`posture-card-state${isFailed ? ' failed' : ''}`} role='status'>
            {unavailableText}
          </span>
        )}
        {Number.isFinite(summary?.valid_tracking_percent) ? (
          <small className='posture-tracking'>Valid tracking: {summary.valid_tracking_percent.toFixed(1)}%</small>
        ) : null}
      </div>
    </button>
  )
}

function MetricTooltip({ active, payload, label, metric }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null

  return (
    <div className='metric-tooltip'>
      <strong>{formatTime(Number(label))}</strong>
      {metric.key === 'shoulder_hiking' ? (
        <>
          {Number.isFinite(point.right_value) ? <span>Right shoulder: {formatMetricValue(point.right_value, metric.unit)}</span> : null}
          {Number.isFinite(point.left_value) ? <span>Left shoulder: {formatMetricValue(point.left_value, metric.unit)}</span> : null}
        </>
      ) : (
        <span>{metric.label}: {formatMetricValue(point.value, metric.unit)}</span>
      )}
      <small>Frame {point.frame}</small>
    </div>
  )
}

function PostureOverTime({ sessionId, metric, summary }) {
  const [series, setSeries] = useState(null)
  const [seriesLoading, setSeriesLoading] = useState(false)
  const [seriesError, setSeriesError] = useState('')
  const [selectedPoint, setSelectedPoint] = useState(null)
  const [keyboardSelection, setKeyboardSelection] = useState(false)
  const [frameUrl, setFrameUrl] = useState('')
  const [frameLoading, setFrameLoading] = useState(false)
  const [frameError, setFrameError] = useState('')
  const canLoad = metricCanLoad(summary)

  useEffect(() => {
    if (!canLoad) {
      setSeries(null)
      setSeriesLoading(false)
      setSeriesError('')
      setSelectedPoint(null)
      return undefined
    }

    const controller = new AbortController()
    let active = true
    setSeries(null)
    setSeriesLoading(true)
    setSeriesError('')
    setSelectedPoint(null)
    stationRequest(
      `/sessions/${encodeURIComponent(sessionId)}/analysis/metrics/${metric.key}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (active) setSeries(result)
      })
      .catch((error) => {
        if (active && !controller.signal.aborted) {
          setSeriesError(error.message || 'Could not load this posture time series.')
        }
      })
      .finally(() => {
        if (active) setSeriesLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [canLoad, metric.key, sessionId])

  useEffect(() => {
    if (!selectedPoint) {
      setFrameUrl('')
      setFrameLoading(false)
      setFrameError('')
      return undefined
    }

    const controller = new AbortController()
    let active = true
    let objectUrl = ''
    setFrameUrl('')
    setFrameLoading(true)
    setFrameError('')
    const url = `${STATION_SERVICE_URL}/sessions/${encodeURIComponent(sessionId)}/analysis/frame?view=${metric.view}&frame=${selectedPoint.frame}`
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          let message = 'Could not load the selected video frame.'
          try {
            const payload = await response.json()
            message = payload.detail || message
          } catch {
            // Keep the readable fallback when the service has no JSON error body.
          }
          throw new Error(message)
        }
        return response.blob()
      })
      .then((blob) => {
        if (!blob.type.startsWith('image/')) {
          throw new Error('The selected frame was not returned as an image.')
        }
        objectUrl = URL.createObjectURL(blob)
        if (active) setFrameUrl(objectUrl)
      })
      .catch((error) => {
        if (active && !controller.signal.aborted) {
          setFrameError(error.message || 'Could not load the selected video frame.')
        }
      })
      .finally(() => {
        if (active) setFrameLoading(false)
      })
    return () => {
      active = false
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [metric.view, selectedPoint, sessionId])

  const selectPoint = (point, channel = 'value', fromKeyboard = false) => {
    const value = point[channel]
    if (!Number.isFinite(value)) return
    setKeyboardSelection(fromKeyboard)
    setSelectedPoint({
      frame: point.frame,
      time_seconds: point.time_seconds,
      channel,
      value,
    })
  }

  const points = series?.points || []
  const unit = series?.unit || summary?.unit || 'degrees'
  const chartMetric = { ...metric, unit }
  const selectedIndex = selectedPoint
    ? points.findIndex((point) => point.frame === selectedPoint.frame)
    : -1
  const onChartKeyDown = (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key) || !points.length) return
    event.preventDefault()
    const direction = event.key === 'ArrowRight' ? 1 : -1
    const nextIndex = Math.max(0, Math.min(points.length - 1, (selectedIndex < 0 ? 0 : selectedIndex) + direction))
    const point = points[nextIndex]
    if (metric.key === 'shoulder_hiking') {
      selectPoint(point, Number.isFinite(point.right_value) ? 'right_value' : 'left_value', true)
    } else {
      selectPoint(point, 'value', true)
    }
  }

  const yValues = points.flatMap((point) => (
    metric.key === 'shoulder_hiking'
      ? [point.right_value, point.left_value]
      : [point.value]
  )).filter(Number.isFinite)
  const yMinimum = yValues.length ? Math.min(...yValues) : 0
  const yMaximum = yValues.length ? Math.max(...yValues) : 1
  const threshold = series?.threshold
  const minimumPadding = unit === 'trunk_length_ratio' ? 0.0005 : 0.05
  const yPadding = Math.max(
    Math.abs(yMaximum - yMinimum) * 0.05,
    Math.abs(threshold || 0) * 0.05,
    minimumPadding,
  )
  const yDomain = Number.isFinite(threshold)
    ? [Math.min(0, yMinimum, threshold) - yPadding, Math.max(yMaximum, threshold) + yPadding]
    : ['auto', 'auto']

  const renderDot = (channel) => (props) => {
    const { cx, cy, payload } = props
    if (!Number.isFinite(cx) || !Number.isFinite(cy) || !Number.isFinite(payload?.[channel])) return null
    const active = selectedPoint?.frame === payload.frame && selectedPoint?.channel === channel
    return (
      <circle
        cx={cx}
        cy={cy}
        r={active ? 5 : 3}
        fill={channel === 'left_value' ? '#d49347' : '#2a688d'}
        stroke='#fff'
        strokeWidth={1}
        tabIndex={-1}
        aria-hidden='true'
        onClick={(event) => {
          event.stopPropagation()
          selectPoint(payload, channel)
        }}
      />
    )
  }

  return (
    <section className='posture-over-time'>
      <div className='posture-over-time-heading'>
        <div>
          <p className='eyebrow'>POSTURE OVER TIME</p>
          <h3>{metric.label}</h3>
        </div>
        {Number.isFinite(series?.threshold) ? (
          <span className='posture-chart-threshold'>Threshold: {formatThreshold(series.threshold, series.unit)}</span>
        ) : null}
      </div>
      <div className='posture-over-time-layout'>
        <div className='card posture-chart-card'>
          {seriesLoading || (canLoad && !series && !seriesError) ? <p className='muted'>Loading posture time series…</p>
            : seriesError ? <p className='posture-load-error' role='alert'>{seriesError}</p>
              : !canLoad ? <p className='muted'>{summary?.reason === 'view_not_recorded' ? 'This view was not recorded.' : 'Posture data is not available yet.'}</p>
                : series?.status === 'insufficient_tracking' || !points.length
                  ? <p className='muted'>Insufficient valid tracking to display this posture over time.</p>
                  : (
                    <>
                      <p className='posture-chart-units'>
                        Session time · {unit === 'degrees' ? 'Degrees' : 'Trunk-length ratio'}
                        {metric.key === 'shoulder_hiking' ? ' · Right and left shoulders' : ''}
                      </p>
                      <div
                        className='posture-chart'
                        tabIndex={0}
                        role='group'
                        aria-label={`${metric.label} time series. Use left and right arrow keys to select frames.`}
                        onKeyDown={onChartKeyDown}
                      >
                        <ResponsiveContainer width='100%' height='100%'>
                          <LineChart data={points} margin={{ top: 12, right: 20, bottom: 10, left: 8 }}>
                            <CartesianGrid strokeDasharray='3 3' stroke='#e8edf1' />
                            <XAxis
                              dataKey='time_seconds'
                              type='number'
                              domain={['dataMin', 'dataMax']}
                              tickFormatter={(value) => formatTime(Number(value))}
                              tick={{ fontSize: 11, fill: '#697683' }}
                              minTickGap={32}
                              label={{ value: 'Session time', position: 'insideBottom', offset: -4, fill: '#697683', fontSize: 12 }}
                            />
                            <YAxis
                              domain={yDomain}
                              tick={{ fontSize: 11, fill: '#697683' }}
                              width={64}
                              label={{
                                value: unit === 'degrees' ? 'Degrees' : 'Trunk-length ratio',
                                angle: -90,
                                position: 'insideLeft',
                                fill: '#697683',
                                fontSize: 12,
                              }}
                            />
                            <Tooltip active={keyboardSelection ? false : undefined} content={<MetricTooltip metric={chartMetric} />} />
                            <ReferenceLine
                              y={series.threshold}
                              stroke='#d89a3b'
                              strokeDasharray='6 4'
                              label={{ value: 'Threshold', position: 'insideTopRight', fill: '#8a5a00', fontSize: 11 }}
                            />
                            {metric.key === 'shoulder_hiking' ? (
                              <>
                                <Line
                                  type='monotone'
                                  dataKey='right_value'
                                  name='Right shoulder'
                                  stroke='#2a688d'
                                  strokeWidth={2}
                                  dot={renderDot('right_value')}
                                  activeDot={false}
                                  isAnimationActive={false}
                                  connectNulls={false}
                                />
                                <Line
                                  type='monotone'
                                  dataKey='left_value'
                                  name='Left shoulder'
                                  stroke='#d49347'
                                  strokeWidth={2}
                                  dot={renderDot('left_value')}
                                  activeDot={false}
                                  isAnimationActive={false}
                                  connectNulls={false}
                                />
                              </>
                            ) : (
                              <Line
                                type='monotone'
                                dataKey='value'
                                name={metric.label}
                                stroke='#2a688d'
                                strokeWidth={2}
                                dot={renderDot('value')}
                                activeDot={false}
                                isAnimationActive={false}
                              />
                            )}
                            {selectedPoint ? (
                              <ReferenceDot
                                x={selectedPoint.time_seconds}
                                y={selectedPoint.value}
                                r={7}
                                fill='#173b57'
                                stroke='#fff'
                                strokeWidth={2}
                              />
                            ) : null}
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                      {metric.key === 'shoulder_hiking' ? (
                        <div className='posture-series-legend'>
                          <span><i className='legend-swatch right' />Right shoulder</span>
                          <span><i className='legend-swatch left' />Left shoulder</span>
                        </div>
                      ) : null}
                    </>
                  )}
        </div>
        <aside className='card selected-frame-card' aria-live='polite'>
          <h4>Selected frame</h4>
          {!selectedPoint ? <p className='muted'>Select a point on the graph to view that moment in the session.</p>
            : frameLoading ? <p className='muted'>Loading selected frame…</p>
              : frameError ? <p className='posture-load-error' role='alert'>{frameError}</p>
                : frameUrl ? <img className='selected-frame-image' src={frameUrl} alt={`Recorded ${viewName(metric.view).toLowerCase()} view at ${formatTime(selectedPoint.time_seconds)}`} />
                  : <p className='muted'>The selected frame is unavailable.</p>}
          {selectedPoint ? (
            <dl className='selected-frame-context'>
              <div><dt>Time</dt><dd>{formatTime(selectedPoint.time_seconds)}</dd></div>
              <div>
                <dt>Metric</dt>
                <dd>
                  {selectedPoint.channel === 'right_value' ? 'Right shoulder: ' : ''}
                  {selectedPoint.channel === 'left_value' ? 'Left shoulder: ' : ''}
                  {formatMetricValue(selectedPoint.value, unit)}
                </dd>
              </div>
              <div><dt>Threshold</dt><dd>{formatThreshold(series?.threshold ?? summary?.threshold, series?.unit || summary?.unit)}</dd></div>
              <div><dt>Frame</dt><dd>{selectedPoint.frame}</dd></div>
            </dl>
          ) : null}
        </aside>
      </div>
    </section>
  )
}

function SessionDetail({ detail, status, recordedAt, retryingView, onRetry }) {
  const [selectedMetric, setSelectedMetric] = useState(POSTURE_METRICS[0].key)
  const initializedSessionId = useRef(null)
  const metadata = detail.metadata || {}
  const overall = statusDisplay(status?.status, status?.stage)
  const views = detail.available_views || []
  const summaries = Object.fromEntries((detail.posture_summaries || []).map((summary) => [summary.metric, summary]))
  const selectedDefinition = POSTURE_METRICS.find((metric) => metric.key === selectedMetric) || POSTURE_METRICS[0]
  const selectedSummary = summaries[selectedDefinition.key]

  useEffect(() => {
    if (detail.session_id === initializedSessionId.current) return
    const summaryList = detail.posture_summaries || []
    const firstReady = POSTURE_METRICS.find((metric) => {
      const summary = summaryList.find((item) => item.metric === metric.key)
      return metricCanLoad(summary)
    })
    const firstRecorded = POSTURE_METRICS.find((metric) => views.includes(metric.view))
    const defaultMetric = views.includes('side')
      ? POSTURE_METRICS[0]
      : firstReady || firstRecorded || POSTURE_METRICS[0]
    setSelectedMetric(defaultMetric.key)
    initializedSessionId.current = detail.session_id
  }, [detail, views])

  return <>
    <Link className='analysis-back' to='/history'>← All sessions</Link>
    <section className='card analysis-detail-header'>
      <div>
        <p className='eyebrow'>SESSION INFORMATION</p>
        <h3>{metadata.session_label || detail.session_id}</h3>
        <p className='muted'>{formatDate(metadata.started_at || metadata.ended_at || metadata.created_at || recordedAt)}</p>
        {metadata.resident_or_study_id ? <p className='muted small'>Resident / Study ID: {metadata.resident_or_study_id}</p> : null}
      </div>
      <div className='analysis-overall-status'>
        <StatusPill tone={overall.tone}>{overall.label}</StatusPill>
        <p className='muted'>{overall.message}</p>
      </div>
    </section>
    <section className='analysis-view-status'>
      <h3>View processing</h3>
      <div className='analysis-view-status-grid'>
        {['side', 'rear'].map((view) => {
          const viewData = detail.views?.[view] || {}
          const viewStatus = status?.views?.[view] || viewData.analysis_status || {}
          const viewRecorded = views.includes(view)
          const canRetry = viewStatus.openpose_status === 'complete'
            && ['failed', 'pending'].includes(viewStatus.posture_status)
            && status?.status !== 'processing'
          return (
            <div className='card analysis-view-status-card' key={view}>
              <div className='analysis-view-status-title'>
                <strong>{viewName(view)} view</strong>
                <StatusPill tone={!viewRecorded ? 'neutral' : viewIsFailed(viewStatus) ? 'warning' : viewStatus.posture_status === 'complete' ? 'success' : 'warning'}>
                  {!viewRecorded ? 'Not recorded' : viewIsFailed(viewStatus) ? 'Needs attention' : stageLabel(viewStatus.posture_status)}
                </StatusPill>
              </div>
              {viewRecorded ? (
                <p className='muted small'>
                  Pose keypoints: {stageLabel(viewStatus.openpose_status)} · Posture analysis: {stageLabel(viewStatus.posture_status)}
                </p>
              ) : <p className='muted small'>No recording is available for this view.</p>}
              {canRetry ? (
                <button className='button secondary' type='button' onClick={() => onRetry(view)} disabled={retryingView === view}>
                  {retryingView === view ? 'Starting…' : 'Retry Analysis'}
                </button>
              ) : null}
            </div>
          )
        })}
      </div>
    </section>
    <section className='posture-summary-section'>
      <div className='posture-section-heading'>
        <div>
          <p className='eyebrow'>POSTURE SUMMARY</p>
          <h3>Research posture exposure</h3>
        </div>
        <p className='posture-threshold-note'>Thresholds shown here are research posture thresholds used by this training prototype, not diagnostic cutoffs.</p>
      </div>
      <div className='posture-summary-grid'>
        {POSTURE_METRICS.map((definition) => {
          const summary = summaries[definition.key]
          const viewStatus = status?.views?.[definition.view] || detail.views?.[definition.view]?.analysis_status || {}
          return (
            <PostureSummaryCard
              key={definition.key}
              definition={definition}
              summary={summary}
              viewStatus={viewStatus}
              overallStatus={status?.status}
              selected={selectedMetric === definition.key}
              onSelect={() => setSelectedMetric(definition.key)}
            />
          )
        })}
      </div>
    </section>
    <PostureOverTime
      key={`${detail.session_id}:${selectedDefinition.key}`}
      sessionId={detail.session_id}
      metric={selectedDefinition}
      summary={selectedSummary}
    />
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
    let lastViewStatuses = JSON.stringify(status.views || {})
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const latest = await stationRequest(`/sessions/${encodeURIComponent(sessionId)}/analysis-status`)
        if (!active) return
        const nextViewStatuses = JSON.stringify(latest.views || {})
        if (
          nextViewStatuses !== lastViewStatuses
          || ['complete', 'failed'].includes(latest.status)
        ) {
          const updated = await stationRequest(`/sessions/${encodeURIComponent(sessionId)}`)
          if (!active) return
          setDetail(updated)
          lastViewStatuses = nextViewStatuses
        }
        setStatus(latest)
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
