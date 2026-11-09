import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { LOW_SCORE_CAPTION, OVERLAY_CAPTION } from '../components/GradCam'
import {
  deferred,
  detail,
  json,
  mockApi,
  png,
  prediction,
  renderApp,
  study,
  type Routes,
} from '../test/helpers'

const noReviews = () => json({ orthanc_study_id: 's1', count: 0, reviews: [] })

function analysedRoutes(label = 1, extra: Routes = {}): Routes {
  return {
    'GET /studies': () => json({ count: 1, studies: [study('s1', { status: 'analysed' })] }),
    'GET /studies/s1/result': () => json(prediction('s1', { label, probability: label ? 0.731234 : 0.2 })),
    'GET /studies/s1/image': () => png(),
    'GET /studies/s1/heatmap': () => png(),
    'GET /studies/s1/reviews': noReviews,
    ...extra,
  }
}

describe('analyse flow', () => {
  it('shows progress while analysing, then the result returned by the API', async () => {
    const pending = deferred<Response>()
    const api = mockApi({
      'GET /studies': () => json({ count: 1, studies: [study('s1', { status: 'pending' })] }),
      'GET /studies/s1/image': () => png(),
      'POST /studies/s1/analyse': () => pending.promise,
      'GET /studies/s1/reviews': noReviews,
    })
    const user = userEvent.setup()
    renderApp('/studies/s1')

    expect(await screen.findByText('Pending analysis')).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: /Chest X-ray for the study ending/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Analyse' }))
    expect(screen.getByRole('button', { name: 'Analysing…' })).toBeDisabled()
    expect(screen.getByText(/Running the model and Grad-CAM/)).toBeInTheDocument()

    pending.resolve(json(prediction('s1')))
    const panel = await screen.findByRole('region', { name: 'Model output' })
    const facts = within(panel)
    expect(facts.getByText('0.7312')).toBeInTheDocument()
    expect(facts.getByText('0.480127')).toBeInTheDocument()
    expect(facts.getByText('(chosen on the validation split, Youden J)')).toBeInTheDocument()
    expect(facts.getByText('1 (at or above 0.480127)')).toBeInTheDocument()
    expect(facts.getByText('A model output, not a diagnosis.')).toBeInTheDocument()
    expect(facts.getByText('densenet121-rsna-pneumonia')).toBeInTheDocument()
    expect(facts.getByText('dfded9ad8bc1')).toHaveAttribute(
      'title',
      'dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9',
    )
    // Regression: the timestamp formatter used to throw and blank the whole panel.
    expect(facts.getByText(/2026/)).toBeInTheDocument()
    expect(screen.getByText('Analysed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Analyse' })).toBeNull()

    expect(api.count('POST', '/studies/s1/analyse')).toBe(1)
    expect(api.count('GET', '/studies/s1/result')).toBe(0)
    expect(api.unmatched).toEqual([])
  })

  it('shows a 503 inline and analyses on retry', async () => {
    let attempt = 0
    mockApi({
      'GET /studies': () => json({ count: 1, studies: [study('s1', { status: 'pending' })] }),
      'GET /studies/s1/image': () => png(),
      'POST /studies/s1/analyse': () =>
        ++attempt === 1 ? detail(503, 'Model not loaded: FileNotFoundError') : json(prediction('s1')),
      'GET /studies/s1/reviews': noReviews,
    })
    const user = userEvent.setup()
    renderApp('/studies/s1')
    await user.click(await screen.findByRole('button', { name: 'Analyse' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Service unavailable')
    expect(alert).toHaveTextContent('Model not loaded: FileNotFoundError')
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('region', { name: 'Model output' })).toBeInTheDocument()
  })

  it('says so when the API returned a stored result instead of a new run', async () => {
    mockApi({
      'GET /studies': () => json({ count: 1, studies: [study('s1', { status: 'pending' })] }),
      'GET /studies/s1/image': () => png(),
      'POST /studies/s1/analyse': () => json(prediction('s1', { cached: true })),
      'GET /studies/s1/reviews': noReviews,
    })
    const user = userEvent.setup()
    renderApp('/studies/s1')
    await user.click(await screen.findByRole('button', { name: 'Analyse' }))
    expect(await screen.findByText(/no new\s+analysis was run/)).toBeInTheDocument()
  })

  it('asks to sync first for a study that is not synced, without fetching its image', async () => {
    const api = mockApi({
      'GET /studies': () => json({ count: 1, studies: [study('s1', { status: 'not_synced' })] }),
    })
    renderApp('/studies/s1')
    expect(await screen.findByText(/has not been synced yet/)).toBeInTheDocument()
    expect(api.count('GET', '/studies/s1/image')).toBe(0)
  })

  it('says when the study is not in Orthanc', async () => {
    mockApi({ 'GET /studies': () => json({ count: 0, studies: [] }) })
    renderApp('/studies/missing')
    expect(await screen.findByText('No study with this ID is in Orthanc.')).toBeInTheDocument()
  })

  it('shows an image error with a retry', async () => {
    let attempt = 0
    mockApi(
      analysedRoutes(1, {
        'GET /studies/s1/image': () => (++attempt === 1 ? detail(502, 'Orthanc returned 500') : png()),
      }),
    )
    const user = userEvent.setup()
    renderApp('/studies/s1')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Orthanc returned an error')
    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('img', { name: /Chest X-ray/ })).toBeInTheDocument()
  })
})

describe('Grad-CAM overlay', () => {
  it('is off by default, with no caption and no heatmap request', async () => {
    const api = mockApi(analysedRoutes())
    renderApp('/studies/s1')
    const toggle = await screen.findByRole('checkbox', { name: 'Show Grad-CAM overlay' })
    expect(toggle).not.toBeChecked()
    expect(screen.getByLabelText('Overlay opacity')).toBeDisabled()
    expect(screen.queryByText(/Highlights regions/)).toBeNull()
    expect(screen.queryByRole('img', { name: /Grad-CAM overlay/ })).toBeNull()
    expect(api.count('GET', '/studies/s1/heatmap')).toBe(0)
  })

  it('shows the overlay with its caption when switched on, fetching the heatmap once', async () => {
    const api = mockApi(analysedRoutes(1))
    const user = userEvent.setup()
    renderApp('/studies/s1')
    const toggle = await screen.findByRole('checkbox', { name: 'Show Grad-CAM overlay' })

    await user.click(toggle)
    const overlay = await screen.findByRole('img', { name: /Grad-CAM overlay/ })
    const caption = screen.getByText(OVERLAY_CAPTION)
    expect(caption).toHaveTextContent(
      'Highlights regions that influenced the pneumonia score. Not a diagnosis. It can also react to markers, borders and positioning.',
    )
    expect(caption).not.toHaveTextContent(LOW_SCORE_CAPTION)
    expect(overlay).toHaveAttribute('aria-describedby', caption.id)

    const slider = screen.getByLabelText('Overlay opacity')
    expect(slider).toBeEnabled()
    fireEvent.change(slider, { target: { value: '80' } })
    expect(overlay).toHaveStyle({ opacity: '0.8' })
    expect(screen.getByText('80%')).toBeInTheDocument()

    await user.click(toggle)
    expect(screen.queryByRole('img', { name: /Grad-CAM overlay/ })).toBeNull()
    expect(screen.queryByText(/Highlights regions/)).toBeNull()
    await user.click(toggle)
    expect(await screen.findByRole('img', { name: /Grad-CAM overlay/ })).toBeInTheDocument()
    expect(api.count('GET', '/studies/s1/heatmap')).toBe(1)
  })

  it('adds the low-score sentence when the label is 0', async () => {
    mockApi(analysedRoutes(0))
    const user = userEvent.setup()
    renderApp('/studies/s1')
    await user.click(await screen.findByRole('checkbox', { name: 'Show Grad-CAM overlay' }))
    const caption = await screen.findByText(/Highlights regions/)
    expect(caption).toHaveTextContent(`${OVERLAY_CAPTION} ${LOW_SCORE_CAPTION}`)
    expect(LOW_SCORE_CAPTION).toBe('Low score: the highlighted areas do not indicate findings.')
  })

  it('shows a 409 checkpoint mismatch without offering a retry', async () => {
    mockApi(
      analysedRoutes(1, {
        'GET /studies/s1/heatmap': () =>
          detail(409, 'Prediction was made with a different checkpoint; re-run analyse with force=true'),
      }),
    )
    const user = userEvent.setup()
    renderApp('/studies/s1')
    await user.click(await screen.findByRole('checkbox', { name: 'Show Grad-CAM overlay' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Conflict')
    expect(alert).toHaveTextContent('different checkpoint')
    expect(within(alert).queryByRole('button')).toBeNull()
  })
})
