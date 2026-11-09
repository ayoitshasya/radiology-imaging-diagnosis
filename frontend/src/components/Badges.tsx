import type { Decision, StudyStatusValue } from '../api/types'

export const STATUS_LABELS: Record<StudyStatusValue, string> = {
  not_synced: 'Not synced',
  pending: 'Pending analysis',
  analysed: 'Analysed',
}

export const DECISION_LABELS: Record<Decision, string> = {
  approved: 'Approved',
  rejected: 'Rejected',
}

/** Workflow status as text in a coloured pill; the text alone carries the meaning. */
export function StatusBadge({ status }: { status: StudyStatusValue }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status]}</span>
}

export function DecisionBadge({ decision }: { decision: Decision | null | undefined }) {
  if (!decision) return <span className="badge badge-none">No review</span>
  return <span className={`badge badge-${decision}`}>{DECISION_LABELS[decision]}</span>
}
