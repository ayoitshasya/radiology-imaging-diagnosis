import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { shortUid } from '../components/ShortUid'
import { deferred, detail, json, mockApi, renderApp, study } from '../test/helpers'
import { filterStudies } from './StudyListPage'

const review = (decision: 'approved' | 'rejected') => ({
  review_id: 1,
  prediction_id: 1,
  decision,
  reviewer: 'A',
  created_at: '2026-11-09T05:00:00Z',
})
const pred = (probability: number, label: number) => ({
  prediction_id: 1,
  probability,
  label,
  threshold: 0.480127,
  created_at: '2026-11-09T05:00:00Z',
})

const STUDIES = [
  study('a1', { status: 'analysed', latest_prediction: pred(0.731234, 1), latest_review: review('approved') }),
  study('b2', { status: 'analysed', latest_prediction: pred(0.2, 0), latest_review: review('rejected') }),
  study('c3', { status: 'pending' }),
  study('d4', { status: 'not_synced' }),
]

function listRoutes() {
  return { 'GET /studies': () => json({ count: STUDIES.length, studies: STUDIES }) }
}

/** The data rows of the table, in order. */
async function rows() {
  const table = await screen.findByRole('table')
  return within(table).getAllByRole('row').slice(1)
}

function rowFor(id: string) {
  const s = STUDIES.find((x) => x.orthanc_study_id === id)!
  return screen.getByRole('link', { name: `Open study, UID ending ${shortUid(s.study_instance_uid)}` }).closest('tr')!
}

describe('study list', () => {
  it('shows each study with a text status badge, probability, label and review', async () => {
    mockApi(listRoutes())
    renderApp('/')
    expect(await rows()).toHaveLength(4)

    const a = within(rowFor('a1'))
    expect(a.getByText('Analysed')).toHaveClass('badge', 'badge-analysed')
    expect(a.getByText('0.7312')).toBeInTheDocument()
    expect(a.getByText('1 (at or above 0.480127)')).toBeInTheDocument()
    expect(a.getByText('Approved')).toHaveClass('badge-approved')

    expect(within(rowFor('b2')).getByText('0 (below 0.480127)')).toBeInTheDocument()
    expect(within(rowFor('b2')).getByText('Rejected')).toBeInTheDocument()
    expect(within(rowFor('c3')).getByText('Pending analysis')).toHaveClass('badge-pending')
    expect(within(rowFor('c3')).getAllByText('Not analysed')).toHaveLength(2)
    expect(within(rowFor('d4')).getByText('Not synced')).toHaveClass('badge-not_synced')
    expect(within(rowFor('d4')).getByText('No review')).toBeInTheDocument()
  })

  it('shows only the last 12 characters of each UID, with a copy button for the full one', async () => {
    mockApi(listRoutes())
    const user = userEvent.setup() // installs a clipboard stub on navigator
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    renderApp('/')
    await rows()
    const full = STUDIES[0]!.study_instance_uid
    expect(document.body.textContent).not.toContain(full)
    await user.click(
      screen.getByRole('button', { name: `Copy full UID of study ending ${shortUid(full)}` }),
    )
    expect(writeText).toHaveBeenCalledWith(full)
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })

  it('filters by status and by latest review decision, together', async () => {
    mockApi(listRoutes())
    const user = userEvent.setup()
    renderApp('/')
    await rows()

    await user.selectOptions(screen.getByLabelText('Status'), 'pending')
    expect(await rows()).toHaveLength(1)
    expect(screen.getByText(/Showing 1 of 4 studies/)).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Status'), '')
    await user.selectOptions(screen.getByLabelText('Latest review'), 'none')
    expect(await rows()).toHaveLength(2)

    await user.selectOptions(screen.getByLabelText('Status'), 'analysed')
    await user.selectOptions(screen.getByLabelText('Latest review'), 'rejected')
    const [only] = await rows()
    expect(within(only!).getByText('Rejected')).toBeInTheDocument()
  })

  it('reads filters from the URL and ignores unknown values', async () => {
    mockApi(listRoutes())
    renderApp('/?status=analysed&decision=approved')
    expect(await rows()).toHaveLength(1)
    expect(screen.getByLabelText('Status')).toHaveValue('analysed')
  })

  it('ignores an unknown filter value in the URL', async () => {
    mockApi(listRoutes())
    renderApp('/?status=bogus')
    expect(await rows()).toHaveLength(4)
  })

  it('says when no study matches and can clear the filters', async () => {
    mockApi(listRoutes())
    const user = userEvent.setup()
    renderApp('/?status=pending&decision=approved')
    expect(await screen.findByText('No studies match these filters.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(await rows()).toHaveLength(4)
  })

  it('syncs from Orthanc, shows the counts from the response and reloads the list', async () => {
    const pending = deferred<Response>()
    const api = mockApi({ ...listRoutes(), 'POST /studies/sync': () => pending.promise })
    const user = userEvent.setup()
    renderApp('/')
    await rows()
    await user.click(screen.getByRole('button', { name: 'Sync from Orthanc' }))
    expect(screen.getByRole('button', { name: 'Syncing from Orthanc…' })).toBeDisabled()

    pending.resolve(
      json({ orthanc_studies: 4, added: 1, already_synced: 2, pending: 1, missing_from_orthanc: 0 }),
    )
    expect(
      await screen.findByText(
        /Sync complete: 1 added, 2 already synced, 1 pending analysis, 0 missing from Orthanc \(\s*4 studies in Orthanc\)/,
      ),
    ).toBeInTheDocument()
    await rows()
    expect(api.count('GET', '/studies')).toBe(2)
  })

  it('points to the upload script when Orthanc has no studies', async () => {
    mockApi({ 'GET /studies': () => json({ count: 0, studies: [] }) })
    renderApp('/')
    expect(await screen.findByText(/No studies in Orthanc yet/)).toBeInTheDocument()
    expect(screen.getByText('python scripts/upload_demo_to_orthanc.py')).toBeInTheDocument()
  })
})

describe('study list errors', () => {
  it('shows a 503 with the backend detail and recovers on retry', async () => {
    let attempt = 0
    mockApi({
      'GET /studies': () =>
        ++attempt === 1
          ? detail(503, 'Orthanc is unreachable')
          : json({ count: STUDIES.length, studies: STUDIES }),
    })
    const user = userEvent.setup()
    renderApp('/')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Service unavailable')
    expect(alert).toHaveTextContent('Orthanc is unreachable')
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await rows()).toHaveLength(4)
  })

  it('reports an unreachable API server', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')))
    renderApp('/')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Cannot reach the API server')
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('never shows the body of a non-JSON server error', async () => {
    mockApi({
      'GET /studies': () => new Response('Traceback (most recent call last): secret', { status: 500 }),
    })
    renderApp('/')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The API returned status 500.')
    expect(alert).not.toHaveTextContent('Traceback')
  })

  it('shows a 502 from sync inline without losing the list', async () => {
    mockApi({ ...listRoutes(), 'POST /studies/sync': () => detail(502, 'Orthanc returned 401') })
    const user = userEvent.setup()
    renderApp('/')
    await rows()
    await user.click(screen.getByRole('button', { name: 'Sync from Orthanc' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Orthanc returned an error')
    expect(alert).toHaveTextContent('Orthanc returned 401')
    expect(await rows()).toHaveLength(4)
  })
})

describe('filterStudies', () => {
  it('treats a missing review as the "none" decision', () => {
    expect(filterStudies(STUDIES, null, 'none').map((s) => s.orthanc_study_id)).toEqual(['c3', 'd4'])
    expect(filterStudies(STUDIES, null, null)).toHaveLength(4)
  })
})
