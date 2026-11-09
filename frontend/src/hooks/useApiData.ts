import { useCallback, useEffect, useState, type DependencyList } from 'react'

export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: unknown }
  | { status: 'ok'; data: T }

/**
 * Loads data from the API when `deps` change, with a reload() for retry buttons.
 *
 * Each load gets its own AbortController; when the page unmounts or deps change, the old
 * request is cancelled and its result ignored, so a slow stale response never overwrites
 * newer data.
 */
export function useApiData<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
): { state: LoadState<T>; reload: () => void } {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: 'ok', data })
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setState({ status: 'error', error })
      },
    )
    return () => controller.abort()
    // `load` is recreated on every render; the caller's deps say when to load again.
  }, [...deps, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  return { state, reload }
}
