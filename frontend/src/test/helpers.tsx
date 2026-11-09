/**
 * Test helpers: a route table that stands in for the backend, data fixtures shaped like the
 * API's responses, and a way to render the whole app at a given URL.
 */
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { App } from '../App'
import type { PredictionOut, StudyStatus } from '../api/types'

export interface Call {
  method: string
  path: string
  query: URLSearchParams
  body: unknown
}

type Reply = Response | Promise<Response>
export type Routes = Record<string, (call: Call) => Reply>

/**
 * Replaces fetch with the given routes, keyed "METHOD /path" (query string excluded).
 * Every request is recorded; one without a route gets a 500 and is listed in `unmatched`
 * so a test can prove no unexpected request was made.
 */
export function mockApi(routes: Routes) {
  const calls: Call[] = []
  const unmatched: string[] = []
  vi.stubGlobal('fetch', (input: string, init?: RequestInit) => {
    const url = new URL(input)
    const method = init?.method ?? 'GET'
    const call: Call = {
      method,
      path: url.pathname,
      query: url.searchParams,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    }
    calls.push(call)
    const handler = routes[`${method} ${url.pathname}`]
    if (!handler) {
      unmatched.push(`${method} ${url.pathname}`)
      return Promise.resolve(Response.json({ detail: 'not mocked' }, { status: 500 }))
    }
    return Promise.resolve(handler(call))
  })
  return {
    calls,
    unmatched,
    count: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path === path).length,
  }
}

export const json = (body: unknown, status = 200) => Response.json(body, { status })
export const png = () => new Response(new Blob(['png'], { type: 'image/png' }))
export const detail = (status: number, text: unknown) => Response.json({ detail: text }, { status })

/** A promise the test resolves by hand, to observe in-progress states. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

/** A digits-and-dots UID whose last 12 characters differ per study ID, as real ones do. */
export function uidFor(id: string): string {
  const digits = [...id].map((c) => c.charCodeAt(0)).join('')
  return `1.2.826.0.1.3680043.8.498.${'4'.repeat(12)}${digits}`
}

export function study(id: string, overrides: Partial<StudyStatus> = {}): StudyStatus {
  return {
    orthanc_study_id: id,
    study_instance_uid: uidFor(id),
    status: 'pending',
    latest_prediction: null,
    latest_review: null,
    ...overrides,
  }
}

export function prediction(id: string, overrides: Partial<PredictionOut> = {}): PredictionOut {
  return {
    notice: 'Educational use only. Not for clinical use.',
    prediction_id: 7,
    orthanc_study_id: id,
    study_instance_uid: uidFor(id),
    probability: 0.731234,
    label: 1,
    label_meaning: 'A model output, not a diagnosis.',
    threshold: 0.480127,
    threshold_source: 'validation split, Youden J',
    model_name: 'densenet121-rsna-pneumonia',
    checkpoint_sha256: 'dfded9ad8bc13b45cc5fff5b4d333326840c87d0a2357ef1b02637ba49ba41e9',
    created_at: '2026-11-09T05:00:00Z',
    cached: false,
    prediction_count: 1,
    latest_review: null,
    ...overrides,
  }
}

export function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}
