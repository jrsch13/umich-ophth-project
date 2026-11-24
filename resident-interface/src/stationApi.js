const stationHost = `${window.location.protocol}//${window.location.hostname}:8000`
export const STATION_SERVICE_URL = (import.meta.env.VITE_STATION_API_URL ?? stationHost).replace(/\/+$/, '')
export const AUTH_EXPIRED = 'station-auth-expired'

export async function stationFetch(path, options) {
  let response
  try {
    response = await fetch(`${STATION_SERVICE_URL}${path}`, { ...options, credentials: 'include' })
  } catch {
    throw new Error('Station service is unavailable. Start the FastAPI backend and try again.')
  }
  if (response.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event(AUTH_EXPIRED))
  }
  return response
}

export async function stationRequest(path, options) {
  const response = await stationFetch(path, options)
  if (response.status === 204) return undefined
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
    const error = new Error(message || 'The station service could not complete the request.')
    error.status = response.status
    throw error
  }

  return payload
}

export function stationPost(path, data, options) {
  return stationRequest(path, {
    ...options,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function stationPlotUrl(path) {
  if (typeof path !== 'string' || !/^\/sessions\/[^/]+\/analysis\/(side|rear)\/plots\/[^/]+\.png$/.test(path)) {
    return null
  }
  return `${STATION_SERVICE_URL}${path}`
}
