import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { NOTICE } from '../notice'
import { json, mockApi, png, prediction, renderApp, study } from '../test/helpers'

function mockEverything() {
  mockApi({
    'GET /studies': () => json({ count: 1, studies: [study('s1', { status: 'analysed' })] }),
    'GET /studies/s1/result': () => json(prediction('s1')),
    'GET /studies/s1/image': () => png(),
    'GET /studies/s1/reviews': () => json({ orthanc_study_id: 's1', count: 0, reviews: [] }),
    'GET /audit': () => json({ total: 0, limit: 25, offset: 0, items: [] }),
  })
}

describe('educational-use banner', () => {
  it.each(['/', '/studies/s1', '/audit', '/no-such-page'])(
    'is shown on %s with the exact notice and nothing that can close it',
    async (path) => {
      mockEverything()
      renderApp(path)
      const banner = screen.getByRole('note', { name: 'Educational use notice' })
      expect(banner).toHaveTextContent(NOTICE)
      expect(NOTICE).toBe('Educational use only. Not for clinical use.')
      expect(within(banner).queryAllByRole('button')).toHaveLength(0)
      expect(within(banner).queryAllByRole('link')).toHaveLength(0)
      // Wait for the page to finish loading, then check nothing anywhere can hide it.
      await screen.findByRole('heading', { level: 1 })
      expect(screen.queryByRole('button', { name: /close|dismiss|hide/i })).toBeNull()
    },
  )

  it('stays in place when navigating between pages', async () => {
    mockEverything()
    const user = userEvent.setup()
    renderApp('/')
    const banner = screen.getByRole('note', { name: 'Educational use notice' })
    await user.click(screen.getByRole('link', { name: 'Audit log' }))
    expect(await screen.findByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Educational use notice' })).toBe(banner)
  })
})
