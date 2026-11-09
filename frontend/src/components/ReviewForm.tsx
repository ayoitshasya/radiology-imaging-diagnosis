import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { FREE_TEXT_MAX, REVIEWER_MAX, type Decision, type ReviewOut } from '../api/types'
import { IDENTIFIER_WARNING } from '../notice'
import { useReviewer } from '../review/ReviewerContext'
import {
  cleanText,
  textLength,
  validateReview,
  type ReviewErrors,
  type ReviewField,
} from '../review/validation'
import { ErrorMessage } from './ErrorMessage'

const FIELD_IDS: Record<ReviewField, string> = {
  decision: 'review-decision-approved',
  reviewer: 'review-reviewer',
  reason: 'review-reason',
  comment: 'review-comment',
}
const ORDER: ReviewField[] = ['decision', 'reviewer', 'reason', 'comment']

interface Props {
  orthancStudyId: string
  predictionId: number
  onSubmitted: (review: ReviewOut) => void
}

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <p id={id} className="field-error">
      Error: {message}
    </p>
  ) : null
}

export function ReviewForm({ orthancStudyId, predictionId, onSubmitted }: Props) {
  const { reviewer, setReviewer } = useReviewer()
  const [decision, setDecision] = useState<Decision | ''>('')
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [errors, setErrors] = useState<ReviewErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState<unknown>(null)
  const [saved, setSaved] = useState<ReviewOut | null>(null)

  function describedBy(field: ReviewField, ...extra: string[]): string {
    return [...extra, errors[field] ? `${FIELD_IDS[field]}-error` : ''].filter(Boolean).join(' ')
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    setSaved(null)
    setServerError(null)
    const { errors: found, body } = validateReview({ decision, reviewer, reason, comment })
    setErrors(found)
    if (!body) {
      const first = ORDER.find((f) => found[f])
      if (first) document.getElementById(FIELD_IDS[first])?.focus()
      return
    }
    setSubmitting(true)
    try {
      const review = await api.submitReview(orthancStudyId, body)
      setSaved(review)
      setDecision('')
      setReason('')
      setComment('')
      onSubmitted(review)
    } catch (err) {
      setServerError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="panel review-form" noValidate onSubmit={submit} aria-labelledby="review-heading">
      <h2 id="review-heading">Review this result</h2>
      <p className="muted">
        Your decision applies to prediction {predictionId}, the latest for this study. Each
        submission adds a new review; earlier ones are never changed.
      </p>

      <fieldset aria-describedby={describedBy('decision')}>
        <legend>Decision</legend>
        <label className="check">
          <input
            id={FIELD_IDS.decision}
            type="radio"
            name="decision"
            value="approved"
            checked={decision === 'approved'}
            aria-invalid={Boolean(errors.decision)}
            onChange={() => setDecision('approved')}
          />
          Approve
        </label>
        <label className="check">
          <input
            type="radio"
            name="decision"
            value="rejected"
            checked={decision === 'rejected'}
            aria-invalid={Boolean(errors.decision)}
            onChange={() => setDecision('rejected')}
          />
          Reject
        </label>
        <FieldError id={`${FIELD_IDS.decision}-error`} message={errors.decision} />
      </fieldset>

      <div className="field">
        <label htmlFor={FIELD_IDS.reviewer}>Reviewer name</label>
        <input
          id={FIELD_IDS.reviewer}
          type="text"
          autoComplete="off"
          value={reviewer}
          aria-invalid={Boolean(errors.reviewer)}
          aria-describedby={describedBy('reviewer', 'reviewer-warning', 'reviewer-hint')}
          onChange={(e) => setReviewer(e.target.value)}
        />
        <p id="reviewer-warning" className="field-warning">
          {IDENTIFIER_WARNING}
        </p>
        <p id="reviewer-hint" className="muted small-text">
          Max {REVIEWER_MAX} characters. Remembered until you reload or close this tab; not
          saved in the browser.
        </p>
        <FieldError id={`${FIELD_IDS.reviewer}-error`} message={errors.reviewer} />
      </div>

      {decision === 'rejected' ? (
        <TextArea
          id={FIELD_IDS.reason}
          label="Reason (required for reject)"
          value={reason}
          onChange={setReason}
          error={errors.reason}
          describedBy={describedBy('reason', 'reason-warning', 'reason-count')}
        />
      ) : null}
      {decision === 'approved' ? (
        <TextArea
          id={FIELD_IDS.comment}
          label="Comment (optional)"
          value={comment}
          onChange={setComment}
          error={errors.comment}
          describedBy={describedBy('comment', 'comment-warning', 'comment-count')}
        />
      ) : null}

      <button type="submit" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Submit review'}
      </button>
      <p role="status" className="muted">
        {saved
          ? `Review ${saved.review_id} saved: ${saved.decision} by ${saved.reviewer}.`
          : ''}
      </p>
      {serverError ? (
        <ErrorMessage error={serverError} onRetry={() => void submit()} />
      ) : null}
    </form>
  )
}

interface TextAreaProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  describedBy: string
}

/** Multi-line free text with the identifier warning and a live character count. */
function TextArea({ id, label, value, onChange, error, describedBy }: TextAreaProps) {
  const prefix = id.replace('review-', '')
  const count = textLength(cleanText(value, true))
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        rows={4}
        value={value}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.value)}
      />
      <p id={`${prefix}-warning`} className="field-warning">
        {IDENTIFIER_WARNING}
      </p>
      <p id={`${prefix}-count`} className={count > FREE_TEXT_MAX ? 'field-error' : 'muted small-text'}>
        {count} of {FREE_TEXT_MAX} characters
      </p>
      <FieldError id={`${id}-error`} message={error} />
    </div>
  )
}
