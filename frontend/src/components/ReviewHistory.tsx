import { api } from '../api/client'
import { formatDateTime } from '../format'
import { useApiData } from '../hooks/useApiData'
import { DecisionBadge } from './Badges'
import { ErrorMessage } from './ErrorMessage'

interface Props {
  orthancStudyId: string
  /** Changed by the page after a submission, to load the history again. */
  refreshKey: number
}

/** GET /studies/{id}/reviews, which the API returns oldest first. */
export function ReviewHistoryList({ orthancStudyId, refreshKey }: Props) {
  const { state, reload } = useApiData((signal) => api.listReviews(orthancStudyId, signal), [
    orthancStudyId,
    refreshKey,
  ])

  return (
    <section className="panel" aria-labelledby="history-heading">
      <h2 id="history-heading">Review history</h2>
      {state.status === 'loading' ? (
        <p role="status">Loading reviews{'…'}</p>
      ) : state.status === 'error' ? (
        <ErrorMessage error={state.error} onRetry={reload} />
      ) : state.data.reviews.length === 0 ? (
        <p>No reviews yet.</p>
      ) : (
        <>
          <p className="muted">
            {state.data.count} {state.data.count === 1 ? 'review' : 'reviews'}, oldest first.
          </p>
          <ol className="history">
            {state.data.reviews.map((r) => (
              <li key={r.review_id}>
                <p>
                  <DecisionBadge decision={r.decision} /> by <strong>{r.reviewer}</strong>,{' '}
                  {formatDateTime(r.created_at)}{' '}
                  <span className="muted">
                    (review {r.review_id}, prediction {r.prediction_id})
                  </span>
                </p>
                {r.reason ? (
                  <p className="free-text">
                    <span className="free-text-label">Reason:</span> {r.reason}
                  </p>
                ) : null}
                {r.comment ? (
                  <p className="free-text">
                    <span className="free-text-label">Comment:</span> {r.comment}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  )
}
