import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ReviewOut } from '../api/types'
import { IDENTIFIER_WARNING } from '../notice'
import { detail, json, mockApi, png, prediction, renderApp, study, type Call } from '../test/helpers'

function reviewOut(body: { decision: 'approved' | 'rejected'; reviewer: string; reason?: string; comment?: string | null }, id: number): ReviewOut {
  return {
    review_id: id,
    prediction_id: 7,
    orthanc_study_id: 's1',
    study_instance_uid: '1.2',
    decision: body.decision,
    reason: body.reason ?? null,
    comment: body.comment ?? null,
    reviewer: body.reviewer,
    created_at: `2026-11-09T05:0${id}:00Z`,
  }
}

/** An analysed study whose review endpoints keep state like the backend does. */
function reviewRoutes(postReply?: (call: Call) => Response) {
  const stored: ReviewOut[] = []
  const api = mockApi({
    'GET /studies': () =>
      json({
        count: 2,
        studies: [study('s1', { status: 'analysed' }), study('s2', { status: 'analysed' })],
      }),
    'GET /studies/s1/result': () => json(prediction('s1')),
    'GET /studies/s2/result': () => json(prediction('s2')),
    'GET /studies/s1/image': () => png(),
    'GET /studies/s2/image': () => png(),
    'GET /studies/s1/reviews': () => json({ orthanc_study_id: 's1', count: stored.length, reviews: stored }),
    'GET /studies/s2/reviews': () => json({ orthanc_study_id: 's2', count: 0, reviews: [] }),
    'POST /studies/s1/review': (call) => {
      if (postReply) return postReply(call)
      const out = reviewOut(call.body as Parameters<typeof reviewOut>[0], stored.length + 1)
      stored.push(out)
      return json(out, 201)
    },
  })
  return { api, stored }
}

async function openForm() {
  const user = userEvent.setup()
  renderApp('/studies/s1')
  await screen.findByRole('form', { name: 'Review this result' })
  return user
}

describe('review validation', () => {
  it('requires a reason to reject: shows the error, focuses the field and sends nothing', async () => {
    const { api } = reviewRoutes()
    const user = await openForm()
    await user.click(screen.getByLabelText('Reject'))
    await user.type(screen.getByLabelText('Reviewer name'), 'Dr A')
    await user.click(screen.getByRole('button', { name: 'Submit review' }))

    expect(screen.getByText('Error: A reason is required when you reject.')).toBeInTheDocument()
    const reason = screen.getByLabelText('Reason (required for reject)')
    expect(reason).toHaveFocus()
    expect(reason).toHaveAttribute('aria-invalid', 'true')
    expect(reason).toHaveAccessibleDescription(expect.stringContaining('A reason is required'))
    expect(api.count('POST', '/studies/s1/review')).toBe(0)
  })

  it('treats a reason of only invisible characters as missing, as the backend does', async () => {
    const { api } = reviewRoutes()
    const user = await openForm()
    await user.click(screen.getByLabelText('Reject'))
    await user.type(screen.getByLabelText('Reviewer name'), 'Dr A')
    await user.type(screen.getByLabelText('Reason (required for reject)'), '​​  ')
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    expect(screen.getByText('Error: A reason is required when you reject.')).toBeInTheDocument()
    expect(api.count('POST', '/studies/s1/review')).toBe(0)
  })

  it('requires a decision and a reviewer name', async () => {
    reviewRoutes()
    const user = await openForm()
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    expect(screen.getByText('Error: Choose approve or reject.')).toBeInTheDocument()
    expect(screen.getByText('Error: Enter your name as reviewer.')).toBeInTheDocument()
    expect(screen.getByLabelText('Approve')).toHaveFocus()
  })

  it('enforces the 1000-character limit after cleaning', async () => {
    const { api } = reviewRoutes()
    const user = await openForm()
    await user.click(screen.getByLabelText('Reject'))
    await user.type(screen.getByLabelText('Reviewer name'), 'Dr A')
    await user.click(screen.getByLabelText('Reason (required for reject)'))
    await user.paste('x'.repeat(1001))
    expect(screen.getByText('1001 of 1000 characters')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    expect(screen.getByText('Error: Reason must be at most 1000 characters.')).toBeInTheDocument()
    expect(api.count('POST', '/studies/s1/review')).toBe(0)
  })

  it('shows the identifier warning on every free-text field', async () => {
    reviewRoutes()
    const user = await openForm()
    expect(screen.getByLabelText('Reviewer name')).toHaveAccessibleDescription(
      expect.stringContaining(IDENTIFIER_WARNING),
    )
    await user.click(screen.getByLabelText('Reject'))
    expect(screen.getByLabelText('Reason (required for reject)')).toHaveAccessibleDescription(
      expect.stringContaining(IDENTIFIER_WARNING),
    )
    await user.click(screen.getByLabelText('Approve'))
    expect(screen.getByLabelText('Comment (optional)')).toHaveAccessibleDescription(
      expect.stringContaining(IDENTIFIER_WARNING),
    )
    expect(screen.getAllByText(IDENTIFIER_WARNING)).toHaveLength(2)
  })
})

describe('review submission and history', () => {
  it('sends a rejection with the cleaned values and refreshes the history', async () => {
    const { api } = reviewRoutes()
    const user = await openForm()
    expect(await screen.findByText('No reviews yet.')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Reject'))
    await user.type(screen.getByLabelText('Reviewer name'), '  Dr​ A ')
    await user.type(screen.getByLabelText('Reason (required for reject)'), 'Marker artefact')
    await user.click(screen.getByRole('button', { name: 'Submit review' }))

    expect(await screen.findByText('Review 1 saved: rejected by Dr A.')).toBeInTheDocument()
    const post = api.calls.find((c) => c.method === 'POST')!
    expect(post.body).toEqual({ decision: 'rejected', reviewer: 'Dr A', reason: 'Marker artefact' })

    const history = screen.getByRole('region', { name: 'Review history' })
    expect(await within(history).findByText('Reason:')).toBeInTheDocument()
    expect(within(history).getByText('Marker artefact', { exact: false })).toBeInTheDocument()
    expect(screen.getByLabelText('Reject')).not.toBeChecked()
    expect(screen.getByLabelText('Reviewer name')).toHaveValue('  Dr​ A ')
  })

  it('sends an approval with an optional comment and never a reason', async () => {
    const { api } = reviewRoutes()
    const user = await openForm()
    await user.click(screen.getByLabelText('Reject'))
    await user.click(screen.getByLabelText('Approve'))
    expect(screen.queryByLabelText('Reason (required for reject)')).toBeNull()
    await user.type(screen.getByLabelText('Reviewer name'), 'Dr B')
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    await screen.findByText(/Review 1 saved/)
    expect(api.calls.find((c) => c.method === 'POST')!.body).toEqual({
      decision: 'approved',
      reviewer: 'Dr B',
      comment: null,
    })
  })

  it('lists reviews oldest first, as the API returns them', async () => {
    reviewRoutes()
    const user = await openForm()
    await user.type(screen.getByLabelText('Reviewer name'), 'First')
    await user.click(screen.getByLabelText('Approve'))
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    await screen.findByText(/Review 1 saved/)
    await user.clear(screen.getByLabelText('Reviewer name'))
    await user.type(screen.getByLabelText('Reviewer name'), 'Second')
    await user.click(screen.getByLabelText('Approve'))
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    await screen.findByText(/Review 2 saved/)

    const history = screen.getByRole('region', { name: 'Review history' })
    await within(history).findByText('2 reviews, oldest first.')
    const items = within(history).getAllByRole('listitem')
    expect(items.map((li) => li.querySelector('strong')?.textContent)).toEqual(['First', 'Second'])
  })

  it('shows a server validation error inline, without a retry', async () => {
    reviewRoutes(() =>
      detail(422, [
        { loc: ['body', 'reviewer'], msg: 'String should have at least 1 character', type: 'string_too_short' },
      ]),
    )
    const user = await openForm()
    await user.click(screen.getByLabelText('Approve'))
    await user.type(screen.getByLabelText('Reviewer name'), 'Dr A')
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Request rejected')
    expect(alert).toHaveTextContent('reviewer: String should have at least 1 character')
    expect(within(alert).queryByRole('button')).toBeNull()
  })

  it('remembers the reviewer name across studies in memory, never in browser storage', async () => {
    reviewRoutes()
    const user = await openForm()
    await user.type(screen.getByLabelText('Reviewer name'), 'Dr A')
    await user.click(screen.getByRole('link', { name: 'Back to studies' }))
    const link = await screen.findAllByRole('link', { name: /Open study/ })
    await user.click(link[1]!)
    await screen.findByRole('form', { name: 'Review this result' })
    expect(screen.getByLabelText('Reviewer name')).toHaveValue('Dr A')
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
  })
})
