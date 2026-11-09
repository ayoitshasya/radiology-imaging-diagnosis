import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { api } from '../api/client'
import {
  DECISIONS,
  STUDY_STATUSES,
  type Decision,
  type StudyStatus,
  type StudyStatusValue,
  type SyncResult,
} from '../api/types'
import { DECISION_LABELS, DecisionBadge, STATUS_LABELS, StatusBadge } from '../components/Badges'
import { ErrorMessage } from '../components/ErrorMessage'
import { ShortUid } from '../components/ShortUid'
import { formatLabel, formatProbability } from '../format'
import { useApiData } from '../hooks/useApiData'

type DecisionFilter = Decision | 'none'

function parseStatus(value: string | null): StudyStatusValue | null {
  return STUDY_STATUSES.find((s) => s === value) ?? null
}

function parseDecision(value: string | null): DecisionFilter | null {
  if (value === 'none') return 'none'
  return DECISIONS.find((d) => d === value) ?? null
}

/** Client-side filtering of the list GET /studies returned; nothing is recomputed. */
export function filterStudies(
  studies: StudyStatus[],
  status: StudyStatusValue | null,
  decision: DecisionFilter | null,
): StudyStatus[] {
  return studies.filter((s) => {
    if (status && s.status !== status) return false
    if (decision) {
      const latest = s.latest_review?.decision ?? 'none'
      if (latest !== decision) return false
    }
    return true
  })
}

function SyncSummary({ result }: { result: SyncResult }) {
  return (
    <p>
      Sync complete: {result.added} added, {result.already_synced} already synced,{' '}
      {result.pending} pending analysis, {result.missing_from_orthanc} missing from Orthanc (
      {result.orthanc_studies} studies in Orthanc).
    </p>
  )
}

export function StudyListPage() {
  const [params, setParams] = useSearchParams()
  const status = parseStatus(params.get('status'))
  const decision = parseDecision(params.get('decision'))
  const { state, reload } = useApiData((signal) => api.listStudies(signal), [])

  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [syncError, setSyncError] = useState<unknown>(null)

  function setFilter(key: 'status' | 'decision', value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  async function sync() {
    setSyncing(true)
    setSyncError(null)
    setSyncResult(null)
    try {
      setSyncResult(await api.syncStudies())
      reload()
    } catch (err) {
      setSyncError(err)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <section aria-labelledby="studies-heading">
      <h1 id="studies-heading">Studies</h1>

      <div className="toolbar">
        <button type="button" onClick={sync} disabled={syncing}>
          {syncing ? 'Syncing from Orthanc…' : 'Sync from Orthanc'}
        </button>
        <div className="field">
          <label htmlFor="status-filter">Status</label>
          <select
            id="status-filter"
            value={status ?? ''}
            onChange={(e) => setFilter('status', e.target.value)}
          >
            <option value="">All statuses</option>
            {STUDY_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="decision-filter">Latest review</label>
          <select
            id="decision-filter"
            value={decision ?? ''}
            onChange={(e) => setFilter('decision', e.target.value)}
          >
            <option value="">All decisions</option>
            {DECISIONS.map((d) => (
              <option key={d} value={d}>
                {DECISION_LABELS[d]}
              </option>
            ))}
            <option value="none">No review</option>
          </select>
        </div>
      </div>

      <div aria-live="polite">
        {syncResult ? <SyncSummary result={syncResult} /> : null}
      </div>
      {syncError ? <ErrorMessage error={syncError} onRetry={sync} /> : null}

      {state.status === 'loading' ? (
        <p role="status">Loading studies{'…'}</p>
      ) : state.status === 'error' ? (
        <ErrorMessage error={state.error} onRetry={reload} />
      ) : (
        <StudyTable
          studies={state.data.studies}
          shown={filterStudies(state.data.studies, status, decision)}
          onClearFilters={() => setParams(new URLSearchParams(), { replace: true })}
        />
      )}
    </section>
  )
}

interface TableProps {
  studies: StudyStatus[]
  shown: StudyStatus[]
  onClearFilters: () => void
}

function StudyTable({ studies, shown, onClearFilters }: TableProps) {
  if (studies.length === 0) {
    return (
      <div className="notice-box">
        <p>
          No studies in Orthanc yet. Upload the demo set with{' '}
          <code>python scripts/upload_demo_to_orthanc.py</code>, then use Sync from Orthanc.
        </p>
      </div>
    )
  }
  if (shown.length === 0) {
    return (
      <div className="notice-box">
        <p>No studies match these filters.</p>
        <button type="button" className="secondary" onClick={onClearFilters}>
          Clear filters
        </button>
      </div>
    )
  }
  return (
    <div className="table-wrap">
      <table>
        <caption>
          Showing {shown.length} of {studies.length} studies. Probabilities are model outputs,
          not diagnoses.
        </caption>
        <thead>
          <tr>
            <th scope="col">Study UID (last 12)</th>
            <th scope="col">Status</th>
            <th scope="col">Probability</th>
            <th scope="col">Label at threshold</th>
            <th scope="col">Latest review</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((s) => (
            <tr key={s.orthanc_study_id}>
              <td>
                <ShortUid
                  uid={s.study_instance_uid}
                  to={`/studies/${encodeURIComponent(s.orthanc_study_id)}`}
                />
              </td>
              <td>
                <StatusBadge status={s.status} />
              </td>
              <td>
                {s.latest_prediction ? (
                  formatProbability(s.latest_prediction.probability)
                ) : (
                  <span className="muted">Not analysed</span>
                )}
              </td>
              <td>
                {s.latest_prediction ? (
                  formatLabel(s.latest_prediction.label, s.latest_prediction.threshold)
                ) : (
                  <span className="muted">Not analysed</span>
                )}
              </td>
              <td>
                <DecisionBadge decision={s.latest_review?.decision} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
