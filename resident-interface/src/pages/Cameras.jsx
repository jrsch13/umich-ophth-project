import { useCallback, useEffect, useMemo, useState } from 'react'
import SectionHeader from '../components/SectionHeader'
import StatusPill from '../components/StatusPill'

const STATION_SERVICE_URL = 'http://127.0.0.1:8000'
const HEADER_SEPARATOR = new TextEncoder().encode('\r\n\r\n')

function findBytes(haystack, needle, fromIndex = 0) {
  for (let index = fromIndex; index <= haystack.length - needle.length; index += 1) {
    let matches = true
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (haystack[index + offset] !== needle[offset]) {
        matches = false
        break
      }
    }
    if (matches) return index
  }
  return -1
}

function appendBytes(left, right) {
  const result = new Uint8Array(left.length + right.length)
  result.set(left)
  result.set(right, left.length)
  return result
}

function CameraPreview({ cameraId, onFailureChange }) {
  const [frameUrl, setFrameUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    let reader
    let lastUrl = ''
    let disposed = false

    const receiveFrames = async () => {
      setFrameUrl('')
      setError('')
      onFailureChange(false)

      try {
        const response = await fetch(
          `${STATION_SERVICE_URL}/cameras/${cameraId}/preview`,
          { signal: controller.signal },
        )
        if (!response.ok) {
          let message = 'Camera preview could not be started.'
          try {
            const payload = await response.json()
            message = payload.detail || message
          } catch {
            // Keep the readable fallback when the service has no JSON error body.
          }
          throw new Error(message)
        }

        const contentType = response.headers.get('content-type') || ''
        const boundaryMatch = contentType.match(/boundary="?([^";]+)"?/i)
        if (!boundaryMatch || !response.body) {
          throw new Error('The station service returned an invalid preview stream.')
        }

        const boundary = new TextEncoder().encode(`--${boundaryMatch[1]}`)
        const readerStream = response.body.getReader()
        reader = readerStream
        let buffer = new Uint8Array(0)
        let receivedFrame = false

        while (true) {
          const { value, done } = await readerStream.read()
          if (done) break
          buffer = appendBytes(buffer, value)

          while (true) {
            const boundaryIndex = findBytes(buffer, boundary)
            if (boundaryIndex < 0) break
            const headerEnd = findBytes(buffer, HEADER_SEPARATOR, boundaryIndex + boundary.length)
            if (headerEnd < 0) break
            const nextBoundary = findBytes(buffer, boundary, headerEnd + HEADER_SEPARATOR.length)
            if (nextBoundary < 0) break

            let frameEnd = nextBoundary
            if (buffer[frameEnd - 2] === 13 && buffer[frameEnd - 1] === 10) {
              frameEnd -= 2
            }
            const frameStart = headerEnd + HEADER_SEPARATOR.length
            if (frameEnd > frameStart) {
              const nextUrl = URL.createObjectURL(
                new Blob([buffer.slice(frameStart, frameEnd)], { type: 'image/jpeg' }),
              )
              if (!disposed) {
                setFrameUrl(nextUrl)
                if (lastUrl) URL.revokeObjectURL(lastUrl)
                lastUrl = nextUrl
                if (!receivedFrame) {
                  receivedFrame = true
                  onFailureChange(false)
                }
              } else {
                URL.revokeObjectURL(nextUrl)
              }
            }
            buffer = buffer.slice(nextBoundary)
          }
        }

        if (!controller.signal.aborted) {
          throw new Error(
            receivedFrame
              ? 'Camera preview ended. The camera may have disconnected.'
              : 'No frames were received from this camera.',
          )
        }
      } catch (previewError) {
        if (!controller.signal.aborted && !disposed) {
          setError(previewError.message || 'Camera preview is unavailable.')
          onFailureChange(true)
        }
      }
    }

    receiveFrames()

    return () => {
      disposed = true
      controller.abort()
      if (reader) reader.cancel().catch(() => {})
      if (lastUrl) URL.revokeObjectURL(lastUrl)
    }
  }, [cameraId, onFailureChange])

  if (error) return <span>{error}</span>
  if (!frameUrl) return <span>Connecting to camera preview...</span>

  return (
    <img
      src={frameUrl}
      alt={`Live preview from camera ${cameraId}`}
      onError={() => {
        setError('Camera preview frame could not be displayed.')
        onFailureChange(true)
      }}
      style={{ width: '100%', height: '100%', minHeight: 250, objectFit: 'contain' }}
    />
  )
}

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
  cameraDetected,
  emptyMessage,
}) {
  const [previewFailed, setPreviewFailed] = useState(false)
  const onFailureChange = useCallback((failed) => setPreviewFailed(failed), [])
  const displayedStatus = previewFailed && value !== null ? 'Needs Attention' : status
  const statusTone = displayedStatus === 'Ready' ? 'success' : 'warning'

  useEffect(() => {
    setPreviewFailed(false)
  }, [value])

  return (
    <section className='card'>
      <div className='camera-title-row'>
        <div>
          <h3>{title}</h3>
          <p className='muted'>{purpose}</p>
        </div>
        <StatusPill tone={statusTone}>{displayedStatus}</StatusPill>
      </div>

      <div className='camera-preview large'>
        {isLoading ? (
          <span>Scanning cameras...</span>
        ) : value === null ? (
          <span>Select a camera to see its live preview.</span>
        ) : !cameraDetected ? (
          <span>Selected camera is not currently detected. Rescan cameras.</span>
        ) : (
          <CameraPreview
            key={value}
            cameraId={value}
            onFailureChange={onFailureChange}
          />
        )}
      </div>

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
    label: `${camera.name || `Camera ${camera.id}`} (Camera ${camera.id}) — ${camera.width ?? '—'} × ${camera.height ?? '—'} @ ${camera.fps ? `${camera.fps} fps` : 'fps n/a'}`,
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
      await new Promise((resolve) => {
        window.requestAnimationFrame(() => window.requestAnimationFrame(resolve))
      })
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
          // purpose='Neck extension + forward lean'
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
          cameraDetected={Boolean(sideCamera)}
          emptyMessage={cameras.length === 0 ? 'No camera available for this view.' : ''}
        />
        <CameraCard
          title='Rear / rear-oblique view'
          // purpose='Shoulder hiking + lateral lean'
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
          cameraDetected={Boolean(rearCamera)}
          emptyMessage={cameras.length === 0 ? 'No camera available for this view.' : ''}
        />
      </div>
    </>
  )
}
