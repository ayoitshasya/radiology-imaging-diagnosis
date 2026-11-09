/**
 * Hand-written types for the FastAPI backend, mirroring docs/openapi.json.
 *
 * They are kept honest in two steps: SCHEMA_FIELDS below must match these types (checked by
 * the TypeScript compiler through `satisfies`), and src/api/types.test.ts checks
 * SCHEMA_FIELDS, the enums and the endpoint list against docs/openapi.json. Fields that
 * OpenAPI marks as not required (those with a server-side default) are optional here too.
 */

export const STUDY_STATUSES = ['not_synced', 'pending', 'analysed'] as const
export type StudyStatusValue = (typeof STUDY_STATUSES)[number]

export const DECISIONS = ['approved', 'rejected'] as const
export type Decision = (typeof DECISIONS)[number]

export const EVENT_TYPES = [
  'study_synced',
  'analysis_completed',
  'analysis_returned_cached',
  'review_submitted',
  'demo_reset',
] as const
export type EventType = (typeof EVENT_TYPES)[number]

/** Free-text limits, matching ReviewIn in the backend. */
export const REVIEWER_MAX = 100
export const FREE_TEXT_MAX = 1000

export interface ReviewSummary {
  review_id: number
  prediction_id: number
  decision: Decision
  reviewer: string
  created_at: string
}

export interface PredictionSummary {
  prediction_id: number
  probability: number
  label: number
  threshold: number
  created_at: string
}

export interface StudyStatus {
  orthanc_study_id: string
  study_instance_uid: string
  status: StudyStatusValue
  latest_prediction?: PredictionSummary | null
  latest_review?: ReviewSummary | null
}

export interface StudyList {
  notice?: string
  count: number
  studies: StudyStatus[]
}

export interface SyncResult {
  notice?: string
  orthanc_studies: number
  added: number
  already_synced: number
  pending: number
  missing_from_orthanc: number
}

export interface PredictionOut {
  notice?: string
  prediction_id: number
  orthanc_study_id: string
  study_instance_uid: string
  probability: number
  label: number
  label_meaning?: string
  threshold: number
  threshold_source?: string
  model_name: string
  checkpoint_sha256: string
  created_at: string
  cached?: boolean
  prediction_count?: number
  latest_review?: ReviewSummary | null
}

export interface ReviewIn {
  decision: Decision
  reviewer: string
  reason?: string | null
  comment?: string | null
}

export interface ReviewOut {
  notice?: string
  review_id: number
  prediction_id: number
  orthanc_study_id: string
  study_instance_uid: string
  decision: Decision
  reason: string | null
  comment: string | null
  reviewer: string
  created_at: string
}

export interface ReviewHistory {
  notice?: string
  orthanc_study_id: string
  count: number
  reviews: ReviewOut[]
}

export interface AuditEntry {
  id: number
  event_type: string
  study_instance_uid: string | null
  detail: Record<string, unknown>
  created_at: string
}

export interface AuditPage {
  notice?: string
  total: number
  limit: number
  offset: number
  items: AuditEntry[]
}

export interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
  input?: unknown
  ctx?: Record<string, unknown>
}

export interface HTTPValidationError {
  detail?: ValidationErrorItem[]
}

/**
 * GET /health. Not in OpenAPI as a schema (the endpoint returns a JSONResponse), so this
 * one is written from backend/app/main.py and is not covered by the schema check.
 */
export interface HealthCheck {
  ok: boolean
  error?: string
  version?: string
  model_name?: string
  checkpoint_sha256?: string
  threshold?: number
}
export interface Health {
  status: 'ok' | 'degraded'
  checks: Record<string, HealthCheck>
  notice: string
}

export interface AuditQuery {
  study_instance_uid?: string
  event_type?: EventType
  since?: string
  until?: string
  limit?: number
  offset?: number
}

// ---- Compile-time description of each schema, compared with OpenAPI in types.test.ts ----

type Kind<V> = V extends string
  ? 'string'
  : V extends number
    ? 'number'
    : V extends boolean
      ? 'boolean'
      : V extends unknown[]
        ? 'array'
        : 'object'

/** For each field: its kind, then `?` if optional, then `|null` if nullable. */
export type FieldSpec<T> = {
  [K in keyof T]-?: `${Kind<NonNullable<T[K]>>}${{} extends Pick<T, K> ? '?' : ''}${null extends T[K] ? '|null' : ''}`
}

export const SCHEMA_FIELDS = {
  ReviewSummary: {
    review_id: 'number',
    prediction_id: 'number',
    decision: 'string',
    reviewer: 'string',
    created_at: 'string',
  } satisfies FieldSpec<ReviewSummary>,
  PredictionSummary: {
    prediction_id: 'number',
    probability: 'number',
    label: 'number',
    threshold: 'number',
    created_at: 'string',
  } satisfies FieldSpec<PredictionSummary>,
  StudyStatus: {
    orthanc_study_id: 'string',
    study_instance_uid: 'string',
    status: 'string',
    latest_prediction: 'object?|null',
    latest_review: 'object?|null',
  } satisfies FieldSpec<StudyStatus>,
  StudyList: {
    notice: 'string?',
    count: 'number',
    studies: 'array',
  } satisfies FieldSpec<StudyList>,
  SyncResult: {
    notice: 'string?',
    orthanc_studies: 'number',
    added: 'number',
    already_synced: 'number',
    pending: 'number',
    missing_from_orthanc: 'number',
  } satisfies FieldSpec<SyncResult>,
  PredictionOut: {
    notice: 'string?',
    prediction_id: 'number',
    orthanc_study_id: 'string',
    study_instance_uid: 'string',
    probability: 'number',
    label: 'number',
    label_meaning: 'string?',
    threshold: 'number',
    threshold_source: 'string?',
    model_name: 'string',
    checkpoint_sha256: 'string',
    created_at: 'string',
    cached: 'boolean?',
    prediction_count: 'number?',
    latest_review: 'object?|null',
  } satisfies FieldSpec<PredictionOut>,
  ReviewIn: {
    decision: 'string',
    reviewer: 'string',
    reason: 'string?|null',
    comment: 'string?|null',
  } satisfies FieldSpec<ReviewIn>,
  ReviewOut: {
    notice: 'string?',
    review_id: 'number',
    prediction_id: 'number',
    orthanc_study_id: 'string',
    study_instance_uid: 'string',
    decision: 'string',
    reason: 'string|null',
    comment: 'string|null',
    reviewer: 'string',
    created_at: 'string',
  } satisfies FieldSpec<ReviewOut>,
  ReviewHistory: {
    notice: 'string?',
    orthanc_study_id: 'string',
    count: 'number',
    reviews: 'array',
  } satisfies FieldSpec<ReviewHistory>,
  AuditEntry: {
    id: 'number',
    event_type: 'string',
    study_instance_uid: 'string|null',
    detail: 'object',
    created_at: 'string',
  } satisfies FieldSpec<AuditEntry>,
  AuditPage: {
    notice: 'string?',
    total: 'number',
    limit: 'number',
    offset: 'number',
    items: 'array',
  } satisfies FieldSpec<AuditPage>,
  HTTPValidationError: {
    detail: 'array?',
  } satisfies FieldSpec<HTTPValidationError>,
} as const
