/**
 * Display formatting only. Every number shown comes from the API; these functions round
 * for display and never compute a value of their own.
 */

/** Model probability to 4 decimals. */
export function formatProbability(p: number): string {
  return p.toFixed(4)
}

/**
 * Threshold to at most 6 decimals (0.480127), so a probability just below it is never
 * displayed as equal to it after rounding.
 */
export function formatThreshold(t: number): string {
  return String(Number(t.toFixed(6)))
}

/** The label returned by the API, explained relative to the threshold it was made with. */
export function formatLabel(label: number, threshold: number): string {
  const t = formatThreshold(threshold)
  return label === 1 ? `1 (at or above ${t})` : `0 (below ${t})`
}

/** Timestamp in the viewer's locale, with the time zone shown. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium', timeZoneName: 'short' })
}
