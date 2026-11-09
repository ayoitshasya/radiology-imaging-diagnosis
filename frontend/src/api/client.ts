/**
 * Typed client for the FastAPI backend. The viewer never talks to Orthanc directly.
 *
 * Every call goes through send(), so all failures arrive as ApiError with the HTTP status
 * (0 when the server cannot be reached) and the backend's `detail`, never as a raw error.
 */
import type {
  AuditPage,
  AuditQuery,
  Health,
  PredictionOut,
  ReviewHistory,
  ReviewIn,
  ReviewOut,
  StudyList,
  SyncResult,
} from './types'

/** Every backend endpoint; types.test.ts checks this list against docs/openapi.json. */
export const ENDPOINTS = [
  'GET /studies',
  'POST /studies/sync',
  'POST /studies/{orthanc_study_id}/analyse',
  'GET /studies/{orthanc_study_id}/result',
  'GET /studies/{orthanc_study_id}/image',
  'GET /studies/{orthanc_study_id}/heatmap',
  'POST /studies/{orthanc_study_id}/review',
  'GET /studies/{orthanc_study_id}/reviews',
  'GET /audit',
  'GET /health',
] as const
export type Endpoint = (typeof ENDPOINTS)[number]

export class ApiError extends Error {
  /** HTTP status, or 0 if the server could not be reached or is not configured. */
  readonly status: number
  /** The backend's `detail` field (a string, or a list of field errors for 422). */
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Base URL from VITE_API_BASE_URL, without a trailing slash. */
export function apiBaseUrl(): string {
  const base: string | undefined = import.meta.env.VITE_API_BASE_URL
  if (!base) {
    throw new ApiError(
      0,
      'VITE_API_BASE_URL is not set. Copy frontend/.env.example to frontend/.env.local.',
    )
  }
  return base.replace(/\/+$/, '')
}

type Query = Record<string, string | number | boolean | undefined>

interface SendOptions {
  id?: string
  query?: Query
  body?: unknown
  signal?: AbortSignal
}

export function buildUrl(endpoint: Endpoint, id?: string, query?: Query): string {
  const template = endpoint.slice(endpoint.indexOf(' ') + 1)
  if (template.includes('{orthanc_study_id}') && !id) {
    throw new ApiError(0, `Missing study ID for ${endpoint}`)
  }
  const path = template.replace('{orthanc_study_id}', () => encodeURIComponent(id ?? ''))
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return `${apiBaseUrl()}${path}${qs ? `?${qs}` : ''}`
}

async function send(endpoint: Endpoint, opts: SendOptions = {}): Promise<Response> {
  const method = endpoint.slice(0, endpoint.indexOf(' '))
  const url = buildUrl(endpoint, opts.id, opts.query)
  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers: opts.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    })
  } catch (err) {
    // A cancelled request is not an error the user needs to see; let the caller ignore it.
    if (err instanceof Error && err.name === 'AbortError') throw err
    throw new ApiError(0, `Cannot reach the API server at ${apiBaseUrl()}.`)
  }
  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? null
    } catch {
      // Non-JSON error bodies (for example a proxy's HTML page) are never shown.
    }
    throw new ApiError(res.status, `Request failed with status ${res.status}`, detail)
  }
  return res
}

async function json<T>(endpoint: Endpoint, opts?: SendOptions): Promise<T> {
  return (await send(endpoint, opts)).json() as Promise<T>
}

async function png(endpoint: Endpoint, opts: SendOptions): Promise<Blob> {
  return (await send(endpoint, opts)).blob()
}

export const api = {
  listStudies: (signal?: AbortSignal) => json<StudyList>('GET /studies', { signal }),
  syncStudies: () => json<SyncResult>('POST /studies/sync'),
  analyse: (id: string, force = false) =>
    json<PredictionOut>('POST /studies/{orthanc_study_id}/analyse', {
      id,
      query: force ? { force: true } : undefined,
    }),
  getResult: (id: string, signal?: AbortSignal) =>
    json<PredictionOut>('GET /studies/{orthanc_study_id}/result', { id, signal }),
  getImage: (id: string, signal?: AbortSignal) =>
    png('GET /studies/{orthanc_study_id}/image', { id, signal }),
  getHeatmap: (id: string, signal?: AbortSignal) =>
    png('GET /studies/{orthanc_study_id}/heatmap', { id, signal }),
  submitReview: (id: string, review: ReviewIn) =>
    json<ReviewOut>('POST /studies/{orthanc_study_id}/review', { id, body: review }),
  listReviews: (id: string, signal?: AbortSignal) =>
    json<ReviewHistory>('GET /studies/{orthanc_study_id}/reviews', { id, signal }),
  getAudit: (query: AuditQuery, signal?: AbortSignal) =>
    json<AuditPage>('GET /audit', { query: { ...query }, signal }),
  getHealth: (signal?: AbortSignal) => json<Health>('GET /health', { signal }),
}
