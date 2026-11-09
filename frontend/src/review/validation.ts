/**
 * Client-side review validation that mirrors backend/app/text.py and ReviewIn, so the user
 * sees the same rules before submitting. The server still validates everything.
 */
import { FREE_TEXT_MAX, REVIEWER_MAX, type Decision, type ReviewIn } from '../api/types'

/**
 * Same cleaning as the backend: normalise newlines, tabs to spaces, drop control (Cc) and
 * invisible format (Cf) characters, keep newlines only where allowed, then trim.
 */
export function cleanText(value: string, allowNewlines: boolean): string {
  const normalised = value.replace(/\r\n?/g, '\n')
  let out = ''
  for (const ch of normalised) {
    if (ch === '\n' && allowNewlines) out += ch
    else if (ch === '\t') out += ' '
    else if (!/^[\p{Cc}\p{Cf}]$/u.test(ch)) out += ch
  }
  return out.trim()
}

/** Length in code points, as Python's len() counts it (an emoji or CJK character is 1). */
export function textLength(value: string): number {
  return [...value].length
}

export interface ReviewDraft {
  decision: Decision | ''
  reviewer: string
  reason: string
  comment: string
}

export type ReviewField = keyof ReviewDraft
export type ReviewErrors = Partial<Record<ReviewField, string>>

/**
 * Validates a draft and builds the request body. A rejection sends only a reason and an
 * approval only an optional comment, matching what the backend accepts.
 */
export function validateReview(draft: ReviewDraft): { errors: ReviewErrors; body: ReviewIn | null } {
  const errors: ReviewErrors = {}
  const reviewer = cleanText(draft.reviewer, false)
  const reason = cleanText(draft.reason, true)
  const comment = cleanText(draft.comment, true)

  if (!draft.decision) errors.decision = 'Choose approve or reject.'
  if (!reviewer) errors.reviewer = 'Enter your name as reviewer.'
  else if (textLength(reviewer) > REVIEWER_MAX)
    errors.reviewer = `Reviewer name must be at most ${REVIEWER_MAX} characters.`
  if (draft.decision === 'rejected') {
    if (!reason) errors.reason = 'A reason is required when you reject.'
    else if (textLength(reason) > FREE_TEXT_MAX)
      errors.reason = `Reason must be at most ${FREE_TEXT_MAX} characters.`
  }
  if (draft.decision === 'approved' && textLength(comment) > FREE_TEXT_MAX)
    errors.comment = `Comment must be at most ${FREE_TEXT_MAX} characters.`

  if (Object.keys(errors).length > 0 || !draft.decision) return { errors, body: null }
  const body: ReviewIn =
    draft.decision === 'rejected'
      ? { decision: 'rejected', reviewer, reason }
      : { decision: 'approved', reviewer, comment: comment || null }
  return { errors, body }
}
