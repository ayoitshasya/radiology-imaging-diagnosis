import { describe, expect, it, vi } from 'vitest'
import { ApiError, api, buildUrl } from './client'
import { describeError } from './errors'

function mockFetch(response: Response | Error) {
  const fn = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (err) {
    if (err instanceof ApiError) return err
    throw err
  }
  throw new Error('expected the call to fail')
}

describe('buildUrl', () => {
  it('encodes the study ID and drops empty query values', () => {
    expect(
      buildUrl('GET /audit', undefined, { event_type: 'demo_reset', since: '', offset: 0 }),
    ).toBe('http://api.test/audit?event_type=demo_reset&offset=0')
    expect(buildUrl('GET /studies/{orthanc_study_id}/result', 'a/b?c')).toBe(
      'http://api.test/studies/a%2Fb%3Fc/result',
    )
  })

  it('refuses a templated endpoint without a study ID', () => {
    expect(() => buildUrl('GET /studies/{orthanc_study_id}/image')).toThrow(ApiError)
  })
})

describe('request failures', () => {
  it('sends POST bodies as JSON and returns the parsed response', async () => {
    const fetchFn = mockFetch(Response.json({ review_id: 1 }, { status: 201 }))
    const out = await api.submitReview('s1', { decision: 'approved', reviewer: 'A' })
    expect(out).toEqual({ review_id: 1 })
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('http://api.test/studies/s1/review')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ decision: 'approved', reviewer: 'A' })
  })

  it('keeps the status and detail of an error response', async () => {
    mockFetch(Response.json({ detail: 'Unknown study; call POST /studies/sync first' }, { status: 404 }))
    const err = await failure(api.getResult('s1'))
    expect(err.status).toBe(404)
    expect(describeError(err)).toEqual({
      title: 'Not found',
      message: 'Unknown study; call POST /studies/sync first',
      retryable: false,
    })
  })

  it('never shows a non-JSON error body', async () => {
    mockFetch(new Response('<html>Traceback (most recent call last)</html>', { status: 500 }))
    const info = describeError(await failure(api.listStudies()))
    expect(info.message).toBe('The API returned status 500.')
    expect(info.retryable).toBe(true)
  })

  it('reports an unreachable server as status 0 with a retry', async () => {
    mockFetch(new TypeError('Failed to fetch'))
    const err = await failure(api.listStudies())
    expect(err.status).toBe(0)
    expect(describeError(err).title).toBe('Cannot reach the API server')
    expect(describeError(err).retryable).toBe(true)
  })

  it('lists 422 field errors without the body/query prefix', async () => {
    mockFetch(
      Response.json(
        { detail: [{ loc: ['body', 'reason'], msg: 'Field required', type: 'missing' }] },
        { status: 422 },
      ),
    )
    const info = describeError(await failure(api.submitReview('s1', { decision: 'rejected', reviewer: 'A' })))
    expect(info).toEqual({ title: 'Request rejected', message: 'reason: Field required', retryable: false })
  })
})
