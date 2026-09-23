/**
 * API client.
 *
 * Session lives in an HttpOnly cookie, so nothing here touches credentials.
 * The CSRF token is held in memory and echoed on every state-changing request.
 */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

let csrfToken = ''
export function setCsrfToken(token: string) {
  csrfToken = token
}
export function getCsrfToken() {
  return csrfToken
}

/** Called when the server says the session is gone, so the UI can react once. */
type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler = () => {}
export function setUnauthorizedHandler(handler: UnauthorizedHandler) {
  onUnauthorized = handler
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }

  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' })

  if (response.status === 401) {
    onUnauthorized()
    throw new ApiError(401, 'Your session has ended. Please log in again.')
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: any) => d.msg).join('; ')
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return (await response.text()) as unknown as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? '{}' : JSON.stringify(body) }),
}

// --- typed shapes the UI relies on ----------------------------------------
export interface CameraSummary {
  key: string
  feed_id: string
  camera_id: string
  name: string
  lat: number | null
  lon: number | null
  heading: number | null
  fov: number | null
  mast_height: number | null
  is_ptz: number
  source: string
  heading_known: boolean
  view_changes_today: number
  latest_frame: { id: number; ts: string; score: number | null; view_changed: number; bbox: string | null } | null
}

export interface FeedHealth {
  feed_id: string
  type: string
  reachable: number
  last_success: string | null
  error_count: number
  last_error: string | null
  camera_count: number
  enabled: number
}

export interface SensorSummary {
  id: string
  name: string
  lat: number
  lon: number
  battery: number | null
  last_seen: string | null
  status: 'nominal' | 'elevated' | 'alarm' | 'unknown'
  latest: SensorReading | null
}

export interface SensorReading {
  id: number
  sensor_id: string
  ts: string
  temp_c: number
  thermal_hotspot: number
  thermal_delta_c: number
  smoke_index: number
  audio_event: number
  battery: number
  demo: number
}

export type EventStatus = 'possible_smoke' | 'verified' | 'sensor_only'

export interface TorchEvent {
  id: number
  ts: string
  updated_at: string
  status: EventStatus
  status_label: string
  category: string
  severity: 'Critical' | 'Warning'
  camera_key: string | null
  camera_name?: string
  sensor_id: string | null
  sensor_name?: string
  frame_id: number | null
  score: number | null
  bbox: number[] | null
  confirmation_detail: string | null
  human_label: 'real' | 'false_alarm' | null
  human_by: string | null
  human_at: string | null
  demo: number
  dispatched_at: string | null
}

export interface UiConfig {
  app_name: string
  map: { token: string; token_problem: string; style: string; center: [number, number]; zoom: number }
  thresholds: { score: number; kill_criteria: Record<string, number> }
  session: { idle_timeout_minutes: number; idle_warning_seconds: number }
  dispatch: { enabled: boolean; using_test_receiver: boolean }
  role: 'viewer' | 'operator' | 'admin'
}

export interface BlindSpotSummary {
  coverage_percent: number
  corridor_acres: number
  blind_acres: number
  seen_acres: number
  proposed_sensors: number
  proposed_coverage_acres: number
  uncovered_after_proposal_acres: number
  placement_capped: boolean
  hardware_cost_usd: number
  sensor_unit_cost_usd: number
  dem_source: string
  dem_is_synthetic: boolean
  area_of_interest: string
  headline: string
  cameras_used: number
}
