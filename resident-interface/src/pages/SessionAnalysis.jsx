import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceArea,
  ReferenceDot,
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
  },
  {
    key: 'shoulder_hiking',
    label: 'Shoulder hiking',
    view: 'rear',
    categoryExplanation: 'RULA adjusts the upper-arm posture score when a shoulder is raised. The right, left, and bilateral classes provide additional feedback from the prototype.',
  },
  {
    key: 'forward_trunk_lean',
    label: 'Forward trunk lean',
    view: 'side',
  },
  {
    key: 'lateral_trunk_lean',
    label: 'Lateral trunk lean',
    view: 'rear',
  },
]

const WITHIN_ZONE_COLOR = '#4d9475'
const OUTSIDE_ZONE_COLOR = '#b94f55'

const RULA_SCORE_COLORS = {
  1: WITHIN_ZONE_COLOR,
  2: '#b59a3d',
  3: '#dc8138',
  4: OUTSIDE_ZONE_COLOR,
}

const STATE_COLORS = {
  shoulder_hiking: {
    Neutral: WITHIN_ZONE_COLOR,
    'Unilateral Right Hiking': '#dc8138',
    'Unilateral Left Hiking': '#b76324',
    'Bilateral Hiking': OUTSIDE_ZONE_COLOR,
  },
  lateral_trunk_lean: {
    False: WITHIN_ZONE_COLOR,
    True: OUTSIDE_ZONE_COLOR,
  },
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
  if (unit === '% of hip width') return `${value.toFixed(2)}% of hip width`
  return `${value.toFixed(2)} ${unit}`
}

function categoryColor(metricKey, category) {
  if (Number.isFinite(category?.rula_score) && RULA_SCORE_COLORS[category.rula_score]) {
    return RULA_SCORE_COLORS[category.rula_score]
  }
  return STATE_COLORS[metricKey]?.[category?.key] || '#7d91a0'
}

function categoryFor(summary, key) {
  return summary?.category_distribution?.find((item) => item.key === key) || null
}

function formatPercent(value) {
  return Number.isFinite(value) ? `${value}%` : 'Unavailable'
}

function PostureDonut({ label, slices }) {
  return (
    <div className='posture-donut'>
      {slices.length ? (
        <div
          role='img'
          aria-label={`${label}. ${slices.map((slice) => `${slice.label}, ${formatPercent(slice.percent)}`).join('. ')}`}
        >
          <PieChart width={108} height={108} aria-hidden='true' accessibilityLayer={false}>
            <Pie
              data={slices}
              dataKey='percent'
              nameKey='label'
              innerRadius={30}
              outerRadius={45}
              stroke='#fff'
              strokeWidth={2}
              isAnimationActive={false}
            >
              {slices.map((slice) => <Cell key={slice.label} fill={slice.color} />)}
            </Pie>
          </PieChart>
        </div>
      ) : (
        <div className='posture-donut-empty' aria-hidden='true'>—</div>
      )}
    </div>
  )
}

function ExposureLegend({ slices }) {
  return (
    <div className='posture-exposure-legend'>
      {slices.map((slice) => (
        <span key={slice.label}>
          <i className='legend-swatch' style={{ backgroundColor: slice.color }} aria-hidden='true' />
          <span>{slice.label}</span>
          <strong>{formatPercent(slice.percent)}</strong>
        </span>
      ))}
    </div>
  )
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
  const exposure = summary?.reference_zone_exposure
  const slices = Number.isFinite(exposure?.within_percent) && Number.isFinite(exposure?.outside_percent)
    ? [
        { label: 'Within reference zone', percent: exposure.within_percent, color: WITHIN_ZONE_COLOR },
        { label: 'Outside reference zone', percent: exposure.outside_percent, color: OUTSIDE_ZONE_COLOR },
      ]
    : []
  const unavailableText = notRecorded
    ? 'View not recorded'
    : isPending
      ? 'Analysis processing'
      : isFailed
        ? 'Analysis needs attention'
        : insufficient
          ? 'Insufficient tracking'
          : 'Analysis data unavailable'

  return (
    <button
      className={`card posture-summary-card${selected ? ' selected' : ''}${canLoad ? '' : ' unavailable'}`}
      type='button'
      disabled={!canLoad}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <PostureDonut label={definition.label} slices={slices} />
      <div className='posture-card-content'>
        <h3>{definition.label}</h3>
        {slices.length ? (
          <ExposureLegend slices={slices} />
        ) : (
          <span className={`posture-card-state${isFailed ? ' failed' : ''}`} role='status'>
            {unavailableText}
          </span>
        )}
        {Number.isFinite(summary?.valid_tracking_percent) ? (
          <small
            className='posture-tracking'
            title={summary.reason === 'category_data_unavailable'
              ? 'No posture categories were saved for this measurement, so none of the trial time could be counted as successfully analyzed.'
              : 'Share of total trial time with a valid result for this measurement. Time is excluded when OpenPose misses required body landmarks, their confidence is too low, or frame data is missing or unusable.'}
          >
            % of Trial Successfully Analyzed: {formatPercent(summary.valid_tracking_percent)} ⓘ
          </small>
        ) : null}
        {exposure?.rule_explanation ? <p className='posture-reference-note'>Reference zone: {exposure.rule_explanation}</p> : null}
      </div>
    </button>
  )
}

function PostureCategoryCard({ metric, summary }) {
  const slices = (summary?.category_distribution || []).map((category) => ({
    label: Number.isFinite(category.rula_score)
      ? `${category.label} · RULA ${category.rula_score}`
      : category.label,
    percent: category.percent_of_valid_time,
    color: categoryColor(metric.key, category),
  }))
  const explanation = metric.categoryExplanation || summary?.reference_zone_exposure?.rule_explanation

  return (
    <section className='card posture-category-card'>
      <h4>RULA category breakdown</h4>
      {slices.length ? (
        <div className='posture-category-content'>
          <PostureDonut label={`${metric.label} categories`} slices={slices} />
          <ExposureLegend slices={slices} />
        </div>
      ) : <p className='muted'>Category data is unavailable for this posture.</p>}
      {explanation ? <p className='posture-reference-note'>{explanation}</p> : null}
    </section>
  )
}

function MetricTooltip({ active, payload, label, metric, summary }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  const category = categoryFor(summary, point.category)

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
      {category ? (
        <span>
          {category.label}
          {Number.isFinite(category.rula_score) ? ` · RULA ${category.rula_score}` : ''}
        </span>
      ) : null}
      <small>Frame {point.frame}</small>
    </div>
  )
}

function categoryBands(points, summary, metricKey) {
  const runs = []
  points.forEach((point, index) => {
    if (!point.category) return
    const previous = runs[runs.length - 1]
    if (previous?.key === point.category) {
      previous.endIndex = index
    } else {
      runs.push({ key: point.category, startIndex: index, endIndex: index })
    }
  })

  return runs.flatMap((run, index) => {
    const next = runs[index + 1]
    const previousPoint = points[run.startIndex - 1]
    const firstPoint = points[run.startIndex]
    const lastPoint = points[run.endIndex]
    const nextPoint = next ? points[next.startIndex] : null
    const followingTime = nextPoint
      ? (lastPoint.time_seconds + nextPoint.time_seconds) / 2
      : lastPoint.time_seconds + (lastPoint.time_seconds - (previousPoint?.time_seconds ?? firstPoint.time_seconds)) / 2
    const x1 = previousPoint
      ? (previousPoint.time_seconds + firstPoint.time_seconds) / 2
      : firstPoint.time_seconds
    const x2 = followingTime
    const category = categoryFor(summary, run.key)
    if (!(x2 > x1) || !category) return []
    return [{
      key: `${metricKey}-${run.startIndex}-${run.key}`,
      x1,
      x2,
      category,
      fill: categoryColor(metricKey, category),
    }]
  })
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
      category: point.category,
      posture_angle_deg: point.posture_angle_deg,
    })
  }

  const points = series?.points || []
  const unit = series?.unit || summary?.unit || 'degrees'
  const chartMetric = { ...metric, unit }
  const bands = categoryBands(points, summary, metric.key)
  const signalLabel = metric.key === 'shoulder_hiking'
    ? '% of hip width'
    : metric.key === 'neck_flexion_extension'
      ? 'Neck flexion/extension (degrees)'
      : 'Change from neutral (degrees)'
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
  const yPadding = Math.max(
    Math.abs(yMaximum - yMinimum) * 0.05,
    unit === '% of hip width' ? 1 : 0.5,
  )
  const yDomain = [yMinimum - yPadding, yMaximum + yPadding]

  const renderDot = (channel) => (props) => {
    const { cx, cy, payload } = props
    if (!Number.isFinite(cx) || !Number.isFinite(cy) || !Number.isFinite(payload?.[channel])) return null
    const active = selectedPoint?.frame === payload.frame && selectedPoint?.channel === channel
    return (
      <circle
        cx={cx}
        cy={cy}
        r={active ? 5 : 3}
        fill={categoryColor(metric.key, categoryFor(summary, payload.category))}
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
  const selectedCategory = categoryFor(summary, selectedPoint?.category)
  const observedCategories = new Set(points.map((point) => point.category).filter(Boolean))
  const chartCategories = (summary?.category_distribution || []).filter(
    (category) => observedCategories.has(category.key),
  )
  return (
    <section className='posture-over-time'>
      <div className='posture-over-time-heading'>
        <div>
          <p className='eyebrow'>POSTURE OVER TIME</p>
          <h3>{metric.label}</h3>
        </div>
      </div>
        <div className='card posture-chart-card'>
          {seriesLoading || (canLoad && !series && !seriesError) ? <p className='muted'>Loading posture time series…</p>
            : seriesError ? <p className='posture-load-error' role='alert'>{seriesError}</p>
              : !canLoad ? <p className='muted'>{summary?.reason === 'view_not_recorded' ? 'This view was not recorded.' : 'Posture data is not available yet.'}</p>
                : series?.status === 'insufficient_tracking' || !points.length
                  ? <p className='muted'>Insufficient valid tracking to display this posture over time.</p>
                  : (
                    <>
                      <p className='posture-chart-units'>
                        Session time · {signalLabel}
                        {metric.key === 'shoulder_hiking' ? ' · Right and left shoulders' : ''}
                        {metric.key === 'forward_trunk_lean' || metric.key === 'lateral_trunk_lean'
                          ? ' · Category bands use backend posture categories'
                          : ''}
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
                            {bands.map((band) => (
                              <ReferenceArea
                                key={band.key}
                                x1={band.x1}
                                x2={band.x2}
                                y1={yDomain[0]}
                                y2={yDomain[1]}
                                fill={band.fill}
                                fillOpacity={0.14}
                                stroke='none'
                              />
                            ))}
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
                                value: unit === '% of hip width' ? unit : 'Degrees',
                                angle: -90,
                                position: 'insideLeft',
                                fill: '#697683',
                                fontSize: 12,
                              }}
                            />
                            <Tooltip
                              active={keyboardSelection ? false : undefined}
                              content={<MetricTooltip metric={chartMetric} summary={summary} />}
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
                      {chartCategories.length ? (
                        <div className='posture-series-category-legend'>
                          {chartCategories.map((category) => (
                            <span key={category.key}>
                              <i
                                className='legend-swatch'
                                style={{ backgroundColor: categoryColor(metric.key, category) }}
                                aria-hidden='true'
                              />
                              {category.label}
                              {Number.isFinite(category.rula_score) ? ` · RULA ${category.rula_score}` : ''}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </>
                  )}
        </div>
      <div className='posture-detail-grid'>
        <PostureCategoryCard metric={metric} summary={summary} />
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
              {metric.key === 'neck_flexion_extension' ? (
                <>
                  <div><dt>Neck angle</dt><dd>{formatMetricValue(selectedPoint.value, unit)}</dd></div>
                  {Number.isFinite(selectedCategory?.rula_score) ? (
                    <div><dt>RULA neck posture score</dt><dd>{selectedCategory.rula_score}</dd></div>
                  ) : null}
                  {selectedCategory ? <div><dt>Category</dt><dd>{selectedCategory.label}</dd></div> : null}
                </>
              ) : null}
              {metric.key === 'forward_trunk_lean' ? (
                <>
                  <div><dt>Forward trunk angle</dt><dd>{formatMetricValue(selectedPoint.posture_angle_deg, unit)}</dd></div>
                  <div><dt>Change from neutral</dt><dd>{formatMetricValue(selectedPoint.value, unit)}</dd></div>
                  {Number.isFinite(selectedCategory?.rula_score) ? (
                    <div><dt>RULA trunk posture score</dt><dd>{selectedCategory.rula_score}</dd></div>
                  ) : null}
                  {selectedCategory ? <div><dt>Category</dt><dd>{selectedCategory.label}</dd></div> : null}
                </>
              ) : null}
              {metric.key === 'lateral_trunk_lean' ? (
                <>
                  <div><dt>Lateral lean</dt><dd>{formatMetricValue(selectedPoint.posture_angle_deg, unit)}</dd></div>
                  {selectedCategory ? <div><dt>RULA side-bending adjustment</dt><dd>{selectedCategory.label}</dd></div> : null}
                </>
              ) : null}
              {metric.key === 'shoulder_hiking' ? (
                <>
                  <div>
                    <dt>Shoulder hiking change</dt>
                    <dd>
                      {selectedPoint.channel === 'right_value' ? 'Right: ' : 'Left: '}
                      {formatMetricValue(selectedPoint.value, unit)}
                    </dd>
                  </div>
                  {selectedCategory ? <div><dt>Classification</dt><dd>{selectedCategory.label}</dd></div> : null}
                  {typeof selectedCategory?.rula_adjustment_present === 'boolean' ? (
                    <div>
                      <dt>RULA raised-shoulder adjustment</dt>
                      <dd>{selectedCategory.rula_adjustment_present ? 'Present' : 'Not present'}</dd>
                    </div>
                  ) : null}
                </>
              ) : null}
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
    const firstAvailable = POSTURE_METRICS.find((metric) => (
      summaryList.some((item) => item.metric === metric.key && item.status === 'available')
    ))
    const neckAvailable = summaryList.some(
      (item) => item.metric === 'neck_flexion_extension' && item.status === 'available',
    )
    const firstRecorded = POSTURE_METRICS.find((metric) => views.includes(metric.view))
    const defaultMetric = neckAvailable
      ? POSTURE_METRICS.find((metric) => metric.key === 'neck_flexion_extension')
      : firstAvailable || firstRecorded || POSTURE_METRICS[0]
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
          <h3>Reference Zone Exposure</h3>
          <p className='posture-method-note'>
            This prototype automates selected posture components from RULA. Reference-zone rules include both RULA categories and project-specific computer-vision detection tolerances. The system does not calculate the complete RULA grand score.
          </p>
          <a
            className='posture-source-link'
            href='https://doi.org/10.1016/0003-6870(93)90080-S'
            target='_blank'
            rel='noreferrer'
          >
            McAtamney &amp; Corlett, Rapid Upper Limb Assessment (RULA), Applied Ergonomics, 1993
          </a>
        </div>
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
