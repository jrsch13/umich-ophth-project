import { useEffect, useMemo, useState } from 'react'
import SectionHeader from '../components/SectionHeader'
import StatusPill from '../components/StatusPill'

const STATION_SERVICE_URL = 'http://127.0.0.1:8000'

function CameraCard({
  title,
  purpose,
  value,
  options,
  onChange,
  status,
  resolution,
  fps,
  isLoading,
  emptyMessage,
}) {
  const statusTone = status === 'Ready' ? 'success' : 'warning'

  return (
    <section className='card'>
      <div className='camera-title-row'>
        <div>
          <h3>{title}</h3>
          <p className='muted'>{purpose}</p>
        </div>
        <StatusPill tone={statusTone}>{status}</StatusPill>
      </div>

      <div className='camera-preview large'>Live preview placeholder</div>

      <label className='field'>
        <span>Camera device</span>
        <select value={value ?? ''} onChange={(event) => onChange(event.target.value === '' ? null : Number(event.target.value))} disabled={isLoading || options.length === 0}>
          <option value=''>Not assigned</option>
          {options.map((camera) => (
            <option key={camera.id} value={camera.id}>
              {camera.label}
            </option>
          ))}
        </select>
      </label>

      <div className='camera-meta'>
        <span>Detected resolution</span>
        <strong>{resolution}</strong>
        <span>Detected frame rate</span>
        <strong>{fps}</strong>
      </div>

      {emptyMessage ? <div className='notice'>{emptyMessage}</div> : null}
    </section>
  )
}

export default function Cameras() {
  const [cameras, setCameras] = useState([])
  const [sideCameraId, setSideCameraId] = useState(null)
  const [rearCameraId, setRearCameraId] = useState(null)
  const [isScanning, setIsScanning] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')

  const cameraLookup = useMemo(
    () => Object.fromEntries(cameras.map((camera) => [camera.id, camera])),
    [cameras],
  )

  const duplicateSelection = sideCameraId !== null && rearCameraId !== null && sideCameraId === rearCameraId

  const sideCamera = sideCameraId !== null ? cameraLookup[sideCameraId] ?? null : null
  const rearCamera = rearCameraId !== null ? cameraLookup[rearCameraId] ?? null : null

  const sideStatus = sideCamera && !duplicateSelection ? 'Ready' : 'Needs Attention'
  const rearStatus = rearCamera && !duplicateSelection ? 'Ready' : 'Needs Attention'

  const sideResolution = sideCamera ? `${sideCamera.width ?? '—'} × ${sideCamera.height ?? '—'}` : 'Not detected'
  const rearResolution = rearCamera ? `${rearCamera.width ?? '—'} × ${rearCamera.height ?? '—'}` : 'Not detected'
  const sideFps = sideCamera ? (sideCamera.fps ? `${sideCamera.fps} fps` : 'FPS unavailable') : 'Not detected'
  const rearFps = rearCamera ? (rearCamera.fps ? `${rearCamera.fps} fps` : 'FPS unavailable') : 'Not detected'

  const cameraOptions = cameras.map((camera) => ({
    id: camera.id,
    label: `Camera ${camera.id} (${camera.width ?? '—'} × ${camera.height ?? '—'} @ ${camera.fps ? `${camera.fps} fps` : 'fps n/a'})`,
  }))

  const filteredSideOptions = cameraOptions.filter((camera) => camera.id !== rearCameraId)
  const filteredRearOptions = cameraOptions.filter((camera) => camera.id !== sideCameraId)

  const loadSavedConfig = async () => {
    try {
      const response = await fetch(`${STATION_SERVICE_URL}/camera-config`)
      if (!response.ok) {
        throw new Error('Saved station configuration could not be loaded.')
      }

      const config = await response.json()
      setSideCameraId(config.side_camera_id ?? null)
      setRearCameraId(config.rear_camera_id ?? null)
    } catch (loadError) {
      setError(loadError.message || 'Saved station configuration could not be loaded.')
    }
  }

  const scanCameras = async () => {
    setIsScanning(true)
    setError('')
    setSaveMessage('')

    try {
      const response = await fetch(`${STATION_SERVICE_URL}/cameras`)
      if (!response.ok) {
        throw new Error('The station service is unavailable or returned an error.')
      }

      const payload = await response.json()
      const availableCameras = Array.isArray(payload.cameras) ? payload.cameras : []
      setCameras(availableCameras)

      if (!availableCameras.length) {
        setError('')
      }
    } catch (scanError) {
      setCameras([])
      setError(scanError.message || 'Could not reach the station service. Start the backend and try again.')
    } finally {
      setIsScanning(false)
    }
  }

  useEffect(() => {
    const bootstrap = async () => {
      await loadSavedConfig()
      await scanCameras()
    }

    bootstrap()
  }, [])

  const saveConfig = async () => {
    if (duplicateSelection) {
      setError('The same camera cannot be assigned to both Side and Rear views.')
      return
    }

    setIsSaving(true)
    setError('')
    setSaveMessage('')

    try {
      const response = await fetch(`${STATION_SERVICE_URL}/camera-config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          side_camera_id: sideCameraId,
          rear_camera_id: rearCameraId,
        }),
      })

      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || 'The station configuration could not be saved.')
      }

      setSaveMessage('Station configuration saved locally.')
    } catch (saveError) {
      setError(saveError.message || 'Could not save the station configuration.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <>
      <SectionHeader
        title='Cameras'
        description='Choose which connected cameras are assigned to each station view.'
        action={
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <button className='button secondary' onClick={scanCameras} disabled={isScanning}>
              {isScanning ? 'Scanning...' : 'Rescan Cameras'}
            </button>
            <button className='button primary' onClick={saveConfig} disabled={isScanning || isSaving}>
              {isSaving ? 'Saving...' : 'Save station configuration'}
            </button>
          </div>
        }
      />

      {error ? <div className='notice' style={{ borderColor: '#f2c4c4', background: '#fff3f3', color: '#8a2f2f' }}>{error}</div> : null}
      {saveMessage ? <div className='notice'>{saveMessage}</div> : null}
      {!isScanning && !cameras.length && !error ? (
        <div className='notice'>No cameras were detected. Plug in a USB camera and use “Rescan Cameras” to check again.</div>
      ) : null}
      {duplicateSelection ? (
        <div className='notice'>The same camera cannot be selected for both the Side and Rear views.</div>
      ) : null}

      <div className='grid two'>
        <CameraCard
          title='Side view'
          purpose='Neck extension + forward lean'
          value={sideCameraId}
          options={filteredSideOptions}
          onChange={(nextValue) => {
            setSaveMessage('')
            setError('')
            setSideCameraId(nextValue)
          }}
          status={sideStatus}
          resolution={sideResolution}
          fps={sideFps}
          isLoading={isScanning}
          emptyMessage={cameras.length === 0 ? 'No camera available for this view.' : ''}
        />
        <CameraCard
          title='Rear / rear-oblique view'
          purpose='Shoulder hiking + lateral lean'
          value={rearCameraId}
          options={filteredRearOptions}
          onChange={(nextValue) => {
            setSaveMessage('')
            setError('')
            setRearCameraId(nextValue)
          }}
          status={rearStatus}
          resolution={rearResolution}
          fps={rearFps}
          isLoading={isScanning}
          emptyMessage={cameras.length === 0 ? 'No camera available for this view.' : ''}
        />
      </div>
    </>
  )
}
