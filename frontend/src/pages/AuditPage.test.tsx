import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuditEntry } from '../api/types'
import { detail, json, mockApi, renderApp } from '../test/helpers'
import { localToUtcIso } from './AuditPage'

function entries(total: number) {
  return Array.from({ length: total }, (_, i): AuditEntry => ({
    id: total - i,
    event_type: i % 2 ? 'review_submitted' : 'analysis_completed',
    study_instance_uid: '1.2.826.0.1.3680043.8.498.123456789012',
    detail: { prediction_id: total - i },
    created_at: '2026-11-09T05:00:00Z',
  }))
}

/** Serves pages of `all` exactly as the API would for the given limit and offset. */
function auditRoutes(all: AuditEntry[]) {
  return mockApi({
    'GET /audit': ({ query }) => {
      const limit = Number(query.get('limit'))
      const offset = Number(query.get('offset'))
      return json({ total: all.length, limit, offset, items: all.slice(offset, offset + limit) })
    },
  })
}

const lastQuery = (api: ReturnType<typeof mockApi>) => api.calls.at(-1)!.query

beforeEach(() => {
  // UTC+5:30 with no daylight saving, so the expected UTC values are fixed.
  // Restored after each test by unstubEnvs in vite.config.ts.
  vi.stubEnv('TZ', 'Asia/Kolkata')
})

describe('audit page', () => {
  it('shows the total, newest first, 25 per page, and pages through', async () => {
    const api = auditRoutes(entries(30))
    const user = userEvent.setup()
    renderApp('/audit')
    expect(await screen.findByText('Events 1 to 25 of 30, newest first.')).toBeInTheDocument()
    expect(lastQuery(api).get('limit')).toBe('25')
    expect(lastQuery(api).get('offset')).toBe('0')
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Next page' }))
    expect(await screen.findByText('Events 26 to 30 of 30, newest first.')).toBeInTheDocument()
    expect(lastQuery(api).get('offset')).toBe('25')
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  })

  it('sends the filters as query parameters, with local times converted to UTC', async () => {
    const api = auditRoutes(entries(3))
    const user = userEvent.setup()
    renderApp('/audit?page=2')
    await screen.findByRole('table').catch(() => undefined)

    await user.type(screen.getByLabelText('Study UID (full)'), '1.2.840.113619')
    await user.selectOptions(screen.getByLabelText('Event type'), 'review_submitted')
    fireEvent.change(screen.getByLabelText('From (your local time, inclusive)'), {
      target: { value: '2026-11-09T10:30' },
    })
    fireEvent.change(screen.getByLabelText('Until (your local time, exclusive)'), {
      target: { value: '2026-11-10T00:00' },
    })
    await user.click(screen.getByRole('button', { name: 'Apply filters' }))
    await screen.findByText(/newest first/)

    const q = lastQuery(api)
    expect(q.get('study_instance_uid')).toBe('1.2.840.113619')
    expect(q.get('event_type')).toBe('review_submitted')
    expect(q.get('since')).toBe('2026-11-09T05:00:00.000Z')
    expect(q.get('until')).toBe('2026-11-09T18:30:00.000Z')
    expect(q.get('offset')).toBe('0') // applying filters goes back to page 1
  })

  it('refuses an invalid UID or a reversed time range without sending a request', async () => {
    const api = auditRoutes(entries(3))
    const user = userEvent.setup()
    renderApp('/audit')
    await screen.findByText(/newest first/)
    const before = api.calls.length

    await user.type(screen.getByLabelText('Study UID (full)'), '1.2.abc')
    fireEvent.change(screen.getByLabelText('From (your local time, inclusive)'), {
      target: { value: '2026-11-10T00:00' },
    })
    fireEvent.change(screen.getByLabelText('Until (your local time, exclusive)'), {
      target: { value: '2026-11-09T00:00' },
    })
    await user.click(screen.getByRole('button', { name: 'Apply filters' }))
    expect(screen.getByText(/Error: A study UID has only digits and dots/)).toBeInTheDocument()
    expect(screen.getByText('Error: From must not be after Until.')).toBeInTheDocument()
    expect(screen.getByLabelText('Study UID (full)')).toHaveAttribute('aria-invalid', 'true')
    expect(api.calls.length).toBe(before)
  })

  it('offers no way to change the log', async () => {
    auditRoutes(entries(3))
    renderApp('/audit')
    await screen.findByText(/newest first/)
    const names = screen.getAllByRole('button').map((b) => b.textContent)
    for (const name of names) {
      expect(name).toMatch(/^(Apply filters|Clear filters|Copy UID|Previous page|Next page)$/)
    }
  })

  it('shows an empty state when nothing matches', async () => {
    auditRoutes([])
    renderApp('/audit?event=demo_reset')
    expect(await screen.findByText('No audit events match these filters.')).toBeInTheDocument()
    expect(screen.getByLabelText('Event type')).toHaveValue('demo_reset')
  })

  it('shows an API error with a retry', async () => {
    let attempt = 0
    mockApi({
      'GET /audit': () =>
        ++attempt === 1 ? detail(503, 'database unavailable') : json({ total: 0, limit: 25, offset: 0, items: [] }),
    })
    const user = userEvent.setup()
    renderApp('/audit')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Service unavailable')
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No audit events match these filters.')).toBeInTheDocument()
  })
})

describe('localToUtcIso', () => {
  it('converts the viewer local time to UTC and leaves empty input unset', () => {
    expect(localToUtcIso('2026-11-09T10:30')).toBe('2026-11-09T05:00:00.000Z')
    expect(localToUtcIso('')).toBeUndefined()
  })
})
