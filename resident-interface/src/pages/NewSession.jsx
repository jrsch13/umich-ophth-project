import { useCallback, useEffect, useMemo, useState } from 'react'
import SectionHeader from '../components/SectionHeader'
import StatusPill from '../components/StatusPill'

const STATION_SERVICE_URL = 'http://127.0.0.1:8000'

async function stationRequest(path, options) {
  let response
  try {
    response = await fetch(`${STATION_SERVICE_URL}${path}`, options)
  } catch {
    throw new Error('Station service is unavailable. Start the FastAPI backend and try again.')
  }
  let payload = {}
  try {
    payload = await response.json()
  } catch {
    // Keep the readable fallback when the service has no JSON error body.
  }

  if (!response.ok) {
    const detail = payload.detail
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(' ')
      : detail
    throw new Error(message || 'The station service could not complete the request.')
  }

  return payload
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainingSeconds = total % 60
  if (hours > 0) {
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
  }
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
}

export default function NewSession() {
  const [phase, setPhase] = useState('setup')
  const [residentId, setResidentId] = useState('TEST001')
  const [sessionLabel, setSessionLabel] = useState('Slit lamp practice')
  const [configuration, setConfiguration] = useState(null)
  const [cameras, setCameras] = useState([])
  const [sessionCameras, setSessionCameras] = useState(null)
  const [serviceReady, setServiceReady] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [countdown, setCountdown] = useState(5)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [sessionId, setSessionId] = useState('')
  const [sessionPath, setSessionPath] = useState('')
  const [error, setError] = useState('')

  const detectedCameraIds = useMemo(
    () => new Set(cameras.map((camera) => camera.id)),
    [cameras],
  )
  const cameraNames = useMemo(
    () => Object.fromEntries(cameras.map((camera) => [camera.id, camera.name])),
    [cameras],
  )

  useEffect(() => {
    let active = true

    const initialize = async () => {
      try {
        const [current, savedConfiguration] = await Promise.all([
          stationRequest('/sessions/current'),
          stationRequest('/camera-config'),
        ])
        if (!active) return

        setServiceReady(true)
        setConfiguration(savedConfiguration)

        if (current.status === 'recording') {
          setPhase('recording')
          setSessionId(current.session_id)
          setSessionCameras(current.selected_cameras ?? {
            side: savedConfiguration.side_camera_id ?? null,
            rear: savedConfiguration.rear_camera_id ?? null,
          })
          setElapsedSeconds(current.elapsed_seconds ?? 0)
          if (current.camera_errors && Object.keys(current.camera_errors).length) {
            setError(Object.values(current.camera_errors).join(' '))
          }
        } else {
          const cameraList = await stationRequest('/cameras')
          if (!active) return
          setCameras(Array.isArray(cameraList.cameras) ? cameraList.cameras : [])
        }
      } catch (loadError) {
        if (active) {
          setError(loadError.message || 'Could not connect to the station service. Start it and refresh this page.')
        }
      } finally {
        if (active) setIsLoading(false)
      }
    }

    initialize()
    return () => {
      active = false
    }
  }, [])

  const startRecording = useCallback(async () => {
    setError('')
    try {
      const result = await stationRequest('/sessions/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resident_id: residentId,
          session_label: sessionLabel,
        }),
      })
      setSessionId(result.session_id)
      setSessionCameras({
        side: configuration?.side_camera_id ?? null,
        rear: configuration?.rear_camera_id ?? null,
      })
      setElapsedSeconds(0)
      setPhase('recording')
    } catch (startError) {
      setError(startError.message || 'Could not start recording.')
      setPhase('setup')
    }
  }, [configuration, residentId, sessionLabel])

  useEffect(() => {
    if (phase !== 'countdown') return undefined

    let remaining = 5
    setCountdown(remaining)
    const timer = window.setInterval(() => {
      if (remaining <= 1) {
        window.clearInterval(timer)
        setCountdown(0)
        startRecording()
      } else {
        remaining -= 1
        setCountdown(remaining)
      }
    }, 1000)

    return () => window.clearInterval(timer)
  }, [phase, startRecording])

  useEffect(() => {
    if (phase !== 'recording') return undefined
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current + 1)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  useEffect(() => {
    if (phase !== 'recording') return undefined
    let active = true
    const refreshStatus = async () => {
      try {
        const current = await stationRequest('/sessions/current')
        if (!active) return
        if (current.status !== 'recording') {
          setError('The station service no longer reports an active recording. Check the session files before continuing.')
          setPhase('setup')
          return
        }
        setElapsedSeconds(current.elapsed_seconds ?? 0)
        const cameraErrors = Object.values(current.camera_errors ?? {})
        if (cameraErrors.length) setError(cameraErrors.join(' '))
      } catch {
        if (active) setError('Could not refresh recording status. Keep the station service running.')
      }
    }

    const timer = window.setInterval(refreshStatus, 2000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [phase])

  const stopRecording = async () => {
    setError('')
    setPhase('saving')
    try {
      const result = await stationRequest('/sessions/stop', { method: 'POST' })
      setSessionId(result.session_id || sessionId)
      setSessionPath(result.session_path || '')
      setPhase('saved')
    } catch (stopError) {
      try {
        const current = await stationRequest('/sessions/current')
        if (current.status === 'recording') {
          setElapsedSeconds(current.elapsed_seconds ?? elapsedSeconds)
          setPhase('recording')
        } else {
          setPhase('setup')
        }
      } catch {
        setPhase('recording')
      }
      setError(stopError.message || 'Could not stop and save the recording.')
    }
  }

  const resetSession = () => {
    setPhase('setup')
    setSessionId('')
    setSessionPath('')
    setElapsedSeconds(0)
    setError('')
  }

  const cameraStatus = (role) => {
    const cameraId = (
      (phase === 'recording' || phase === 'saving') && sessionCameras
        ? sessionCameras[role]
        : configuration?.[`${role}_camera_id`]
    ) ?? null
    if (cameraId === null) return { text: 'Not configured', tone: 'neutral', detail: '' }
    if (
      (phase === 'recording' || phase === 'saving')
      && sessionCameras?.[role] === cameraId
    ) {
      return { text: 'Recording', tone: 'success', detail: `Camera ${cameraId}` }
    }
    const name = cameraNames[cameraId]
    if (detectedCameraIds.has(cameraId)) {
      return {
        text: 'Ready',
        tone: 'success',
        detail: name ? `${name} (Camera ${cameraId})` : `Camera ${cameraId}`,
      }
    }
    return {
      text: 'Disconnected',
      tone: 'warning',
      detail: `Configured camera ${cameraId} was not detected`,
    }
  }

  const sideStatus = cameraStatus('side')
  const rearStatus = cameraStatus('rear')
  const configuredIds = [
    configuration?.side_camera_id ?? null,
    configuration?.rear_camera_id ?? null,
  ].filter((cameraId) => cameraId !== null)
  const canStart = serviceReady
    && configuredIds.length > 0
    && configuredIds.every((cameraId) => detectedCameraIds.has(cameraId))

  return (
    <>
      <SectionHeader
        title='New Session'
        description='Set up a recording session using the cameras assigned to this station.'
      />

      {error ? (
        <div className='notice' style={{ borderColor: '#f2c4c4', background: '#fff3f3', color: '#8a2f2f' }}>
          {error}
        </div>
      ) : null}
      {!isLoading && serviceReady && configuredIds.length === 0 && phase === 'setup' ? (
        <div className='notice'>No camera is configured. Assign at least one camera on the Cameras page before starting.</div>
      ) : null}
      {!isLoading && serviceReady && configuredIds.length > 0 && !canStart && phase === 'setup' ? (
        <div className='notice'>A configured camera is not currently available. Reconnect it and check the Cameras page before starting.</div>
      ) : null}

      <div className='grid two'>
        <section className='card'>
          <h3>Session setup</h3>
          <label className='field'>
            <span>Resident / Study ID</span>
            <input
              value={residentId}
              onChange={(event) => setResidentId(event.target.value)}
              disabled={phase !== 'setup' || isLoading}
              required
            />
          </label>
          <label className='field'>
            <span>Session label</span>
            <input
              value={sessionLabel}
              onChange={(event) => setSessionLabel(event.target.value)}
              disabled={phase !== 'setup' || isLoading}
              required
            />
          </label>

          <div className='status-row'>
            <span>Side camera{sideStatus.detail ? ` · ${sideStatus.detail}` : ''}</span>
            <StatusPill tone={sideStatus.tone}>{sideStatus.text}</StatusPill>
          </div>
          <div className='status-row'>
            <span>Rear camera{rearStatus.detail ? ` · ${rearStatus.detail}` : ''}</span>
            <StatusPill tone={rearStatus.tone}>{rearStatus.text}</StatusPill>
          </div>

          {phase === 'setup' ? (
            <button
              className='button primary full'
              onClick={() => {
                setError('')
                setPhase('countdown')
              }}
              disabled={isLoading || !canStart || !residentId.trim() || !sessionLabel.trim()}
            >
              START SESSION
            </button>
          ) : null}
          {phase === 'countdown' ? (
            <button className='button secondary full' onClick={() => setPhase('setup')}>
              Cancel countdown
            </button>
          ) : null}
        </section>

        <section className='card'>
          {isLoading ? <p>Loading station configuration...</p> : null}
          {!isLoading && phase === 'setup' ? (
            <>
              <h3>Ready to record</h3>
              <p className='muted'>The station service will record each configured camera to a local session folder.</p>
            </>
          ) : null}
          {phase === 'countdown' ? (
            <div style={{ textAlign: 'center', padding: '22px 0' }}>
              <h3>Recording starts in</h3>
              <strong style={{ display: 'block', fontSize: '64px', color: '#173b57' }}>{countdown}</strong>
            </div>
          ) : null}
          {phase === 'recording' ? (
            <div style={{ textAlign: 'center', padding: '22px 0' }}>
              <StatusPill tone='success'>● RECORDING</StatusPill>
              <strong style={{ display: 'block', fontSize: '42px', margin: '20px 0', color: '#173b57' }}>
                {formatElapsed(elapsedSeconds)}
              </strong>
              <p className='muted'>{sessionId}</p>
              <button className='button primary' onClick={stopRecording}>STOP SESSION</button>
            </div>
          ) : null}
          {phase === 'saving' ? (
            <div style={{ textAlign: 'center', padding: '42px 0' }}>
              <h3>Saving session...</h3>
              <p className='muted'>Closing camera files and writing session metadata.</p>
            </div>
          ) : null}
          {phase === 'saved' ? (
            <div style={{ textAlign: 'center', padding: '22px 0' }}>
              <StatusPill tone='success'>Session saved ✓</StatusPill>
              <h3>Recording complete.</h3>
              <p className='muted'>{sessionId}</p>
              {sessionPath ? <p className='muted small'>{sessionPath}</p> : null}
              <button className='button secondary' onClick={resetSession}>New session</button>
            </div>
          ) : null}
        </section>
      </div>
    </>
  )
}
