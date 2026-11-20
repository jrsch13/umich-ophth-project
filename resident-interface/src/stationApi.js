export const STATION_SERVICE_URL = 'http://127.0.0.1:8000'

export async function stationRequest(path, options) {
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

export function stationPlotUrl(path) {
  if (typeof path !== 'string' || !/^\/sessions\/[^/]+\/analysis\/(side|rear)\/plots\/[^/]+\.png$/.test(path)) {
    return null
  }
  return `${STATION_SERVICE_URL}${path}`
}
