import { describeError } from '../api/errors'

interface Props {
  error: unknown
  /** Offered only when the error is one that retrying can fix (network, 502, 503, 5xx). */
  onRetry?: () => void
}

export function ErrorMessage({ error, onRetry }: Props) {
  const info = describeError(error)
  return (
    <div className="error" role="alert">
      <p className="error-title">{info.title}</p>
      <p>{info.message}</p>
      {info.retryable && onRetry ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}
