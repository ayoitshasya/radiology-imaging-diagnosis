import { describe, expect, it } from 'vitest'
import { cleanText, textLength, validateReview } from './validation'

/**
 * [input, clean_text(allow_newlines=True), clean_text(allow_newlines=False), len(...)],
 * copied from running backend/app/text.py clean_text on these inputs (2026-11-09), so the
 * client rules are pinned to the server's actual behaviour.
 */
const BACKEND: [string, string, string, number][] = [
  ['  Dr​ A\t B ', 'Dr A  B', 'Dr A  B', 7],
  ['line1\r\nline2\rline3', 'line1\nline2\nline3', 'line1line2line3', 17],
  ['‮evil‬ ok', 'evil ok', 'evil ok', 7],
  ['\u{1F600}x', '\u{1F600}x', '\u{1F600}x', 2],
  ['​​', '', '', 0],
  ['a\u0000b\u0007c', 'abc', 'abc', 3],
]

describe('cleanText matches backend clean_text', () => {
  it.each(BACKEND)('%j', (input, multi, single, length) => {
    expect(cleanText(input, true)).toBe(multi)
    expect(cleanText(input, false)).toBe(single)
    expect(textLength(cleanText(input, true))).toBe(length)
  })
})

describe('validateReview', () => {
  const base = { reviewer: 'Dr A', reason: '', comment: '' }

  it('builds a rejection body with only the reason', () => {
    const { errors, body } = validateReview({ ...base, decision: 'rejected', reason: ' why ', comment: 'ignored' })
    expect(errors).toEqual({})
    expect(body).toEqual({ decision: 'rejected', reviewer: 'Dr A', reason: 'why' })
  })

  it('builds an approval body with only the comment, null when empty', () => {
    expect(validateReview({ ...base, decision: 'approved', reason: 'ignored' }).body).toEqual({
      decision: 'approved',
      reviewer: 'Dr A',
      comment: null,
    })
  })

  it('counts length in code points, as the backend does', () => {
    const emoji = '\u{1F600}'.repeat(1000) // 2000 UTF-16 units, 1000 code points
    expect(validateReview({ ...base, decision: 'rejected', reason: emoji }).errors).toEqual({})
    expect(validateReview({ ...base, decision: 'rejected', reason: `${emoji}x` }).errors.reason).toBe(
      'Reason must be at most 1000 characters.',
    )
    expect(validateReview({ ...base, decision: 'approved', reviewer: 'r'.repeat(101) }).errors.reviewer).toBe(
      'Reviewer name must be at most 100 characters.',
    )
  })
})
