import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { api } from '../api/client'
import { EVENT_TYPES, type AuditEntry, type AuditQuery, type EventType } from '../api/types'
import { ErrorMessage } from '../components/ErrorMessage'
import { ShortUid } from '../components/ShortUid'
import { formatDateTime } from '../format'
import { useApiData } from '../hooks/useApiData'

export const PAGE_SIZE = 25
const UID_PATTERN = /^[0-9.]+$/
const UID_MAX = 64

export const EVENT_LABELS: Record<EventType, string> = {
  study_synced: 'Study synced',
  analysis_completed: 'Analysis completed',
  analysis_returned_cached: 'Stored analysis returned',
  review_submitted: 'Review submitted',
  demo_reset: 'Demo reset',
}

interface Filters {
  uid: string
  event: EventType | ''
  from: string
  until: string
}

function readFilters(params: URLSearchParams): Filters {
  const event = EVENT_TYPES.find((e) => e === params.get('event')) ?? ''
  return {
    uid: params.get('uid') ?? '',
    event,
    from: params.get('from') ?? '',
    until: params.get('until') ?? '',
  }
}

/**
 * A datetime-local value ("2026-11-09T10:30", the viewer's local time) as a UTC ISO string.
 * The backend reads a timestamp without a zone as UTC, so sending the local value as is
 * would shift the filter by the viewer's UTC offset.
 */
export function localToUtcIso(local: string): string | undefined {
  if (!local) return undefined
  const d = new Date(local)
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString()
}

/** The same rules the backend applies to the query, checked before sending. */
export function validateFilters(f: Filters): Partial<Record<keyof Filters, string>> {
  const errors: Partial<Record<keyof Filters, string>> = {}
  const uid = f.uid.trim()
  if (uid && (!UID_PATTERN.test(uid) || uid.length > UID_MAX))
    errors.uid = `A study UID has only digits and dots, at most ${UID_MAX} characters.`
  const since = localToUtcIso(f.from)
  const until = localToUtcIso(f.until)
  if (f.from && !since) errors.from = 'Enter a valid date and time.'
  if (f.until && !until) errors.until = 'Enter a valid date and time.'
  if (since && until && since > until) errors.from = 'From must not be after Until.'
  return errors
}

function toQuery(f: Filters, page: number): AuditQuery {
  return {
    study_instance_uid: f.uid.trim() || undefined,
    event_type: f.event || undefined,
    since: localToUtcIso(f.from),
    until: localToUtcIso(f.until),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  }
}

export function AuditPage() {
  const [params, setParams] = useSearchParams()
  const applied = readFilters(params)
  const page = Math.max(1, Number.parseInt(params.get('page') ?? '1', 10) || 1)
  const appliedValid = Object.keys(validateFilters(applied)).length === 0

  const [draft, setDraft] = useState<Filters>(applied)
  const [errors, setErrors] = useState<Partial<Record<keyof Filters, string>>>({})

  // Back/forward changes the URL; keep the inputs showing the filters actually applied.
  const paramKey = params.toString()
  useEffect(() => {
    const fromUrl = readFilters(new URLSearchParams(paramKey))
    setDraft(fromUrl)
    setErrors(validateFilters(fromUrl))
  }, [paramKey])

  // Only valid filters are sent; a hand-edited URL with bad values shows the form errors.
  const { state, reload } = useApiData(
    (signal) =>
      appliedValid ? api.getAudit(toQuery(applied, page), signal) : Promise.resolve(null),
    [paramKey],
  )

  function navigate(f: Filters, nextPage: number) {
    const next = new URLSearchParams()
    if (f.uid.trim()) next.set('uid', f.uid.trim())
    if (f.event) next.set('event', f.event)
    if (f.from) next.set('from', f.from)
    if (f.until) next.set('until', f.until)
    if (nextPage > 1) next.set('page', String(nextPage))
    setParams(next)
  }

  function apply(event: FormEvent) {
    event.preventDefault()
    const found = validateFilters(draft)
    setErrors(found)
    if (Object.keys(found).length === 0) navigate(draft, 1)
  }

  function clear() {
    const empty: Filters = { uid: '', event: '', from: '', until: '' }
    setDraft(empty)
    setErrors({})
    navigate(empty, 1)
  }

  function field(key: keyof Filters) {
    return {
      'aria-invalid': Boolean(errors[key]),
      'aria-describedby': errors[key] ? `audit-${key}-error` : undefined,
    }
  }

  return (
    <section aria-labelledby="audit-heading">
      <h1 id="audit-heading">Audit log</h1>
      <p className="muted">
        Read-only. Every sync, analysis, review and demo reset is recorded here; entries are
        never edited or deleted.
      </p>

      <form className="toolbar audit-filters" onSubmit={apply} noValidate aria-label="Audit filters">
        <div className="field">
          <label htmlFor="audit-uid">Study UID (full)</label>
          <input
            id="audit-uid"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={draft.uid}
            onChange={(e) => setDraft({ ...draft, uid: e.target.value })}
            {...field('uid')}
          />
          {errors.uid ? <p id="audit-uid-error" className="field-error">Error: {errors.uid}</p> : null}
        </div>
        <div className="field">
          <label htmlFor="audit-event">Event type</label>
          <select
            id="audit-event"
            value={draft.event}
            onChange={(e) =>
              setDraft({ ...draft, event: EVENT_TYPES.find((t) => t === e.target.value) ?? '' })
            }
          >
            <option value="">All events</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {EVENT_LABELS[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="audit-from">From (your local time, inclusive)</label>
          <input
            id="audit-from"
            type="datetime-local"
            step={1}
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
            {...field('from')}
          />
          {errors.from ? <p id="audit-from-error" className="field-error">Error: {errors.from}</p> : null}
        </div>
        <div className="field">
          <label htmlFor="audit-until">Until (your local time, exclusive)</label>
          <input
            id="audit-until"
            type="datetime-local"
            step={1}
            value={draft.until}
            onChange={(e) => setDraft({ ...draft, until: e.target.value })}
            {...field('until')}
          />
          {errors.until ? <p id="audit-until-error" className="field-error">Error: {errors.until}</p> : null}
        </div>
        <button type="submit">Apply filters</button>
        <button type="button" className="secondary" onClick={clear}>
          Clear filters
        </button>
      </form>

      {!appliedValid ? (
        <div className="notice-box">
          <p>The filters in this address are not valid. Correct them above and apply again.</p>
        </div>
      ) : state.status === 'loading' ? (
        <p role="status">Loading audit events{'…'}</p>
      ) : state.status === 'error' ? (
        <ErrorMessage error={state.error} onRetry={reload} />
      ) : state.data ? (
        <AuditTable
          page={page}
          total={state.data.total}
          items={state.data.items}
          onPage={(p) => navigate(applied, p)}
        />
      ) : null}
    </section>
  )
}

interface TableProps {
  page: number
  total: number
  items: AuditEntry[]
  onPage: (page: number) => void
}

function AuditTable({ page, total, items, onPage }: TableProps) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  if (total === 0) {
    return (
      <div className="notice-box">
        <p>No audit events match these filters.</p>
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <div className="notice-box">
        <p>
          Page {page} is past the end ({total} events in {pages} pages).
        </p>
        <button type="button" className="secondary" onClick={() => onPage(1)}>
          Go to page 1
        </button>
      </div>
    )
  }
  const first = (page - 1) * PAGE_SIZE + 1
  const last = first + items.length - 1
  return (
    <>
      <div className="table-wrap">
        <table>
          <caption>
            Events {first} to {last} of {total}, newest first.
          </caption>
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">Time</th>
              <th scope="col">Event</th>
              <th scope="col">Study UID (last 12)</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id}>
                <td>{e.id}</td>
                <td>{formatDateTime(e.created_at)}</td>
                <td>{EVENT_LABELS[e.event_type as EventType] ?? e.event_type}</td>
                <td>
                  {e.study_instance_uid ? (
                    <ShortUid uid={e.study_instance_uid} />
                  ) : (
                    <span className="muted">None</span>
                  )}
                </td>
                <td>
                  {/* Scrollable, so focusable: keyboard users can scroll long details too. */}
                  <pre className="audit-detail" tabIndex={0} aria-label={`Details of event ${e.id}`}>
                    {JSON.stringify(e.detail, null, 2)}
                  </pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav className="pager" aria-label="Audit log pages">
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous page
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button type="button" className="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next page
        </button>
      </nav>
    </>
  )
}
