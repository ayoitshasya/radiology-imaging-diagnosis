import { formatProbability, formatThreshold } from '../format'

function percent(x: number): number {
  return Math.min(1, Math.max(0, x)) * 100
}

/**
 * The model probability on a 0 to 1 scale with a marker at the decision threshold.
 *
 * The bar is decoration only (aria-hidden): the same two numbers are always printed as text
 * next to it, so neither colour nor position is the only way to read the result. The fill
 * uses a neutral colour so the bar does not suggest healthy or diseased.
 */
export function ProbabilityBar({ probability, threshold }: { probability: number; threshold: number }) {
  const t = percent(threshold)
  return (
    <div className="prob" aria-hidden="true">
      <div className="prob-track">
        <div className="prob-fill" style={{ width: `${percent(probability)}%` }} />
        <div className="prob-marker" style={{ left: `${t}%` }} />
      </div>
      <div className="prob-scale">
        <span>0</span>
        <span className="prob-marker-label" style={{ left: `${t}%` }}>
          threshold {formatThreshold(threshold)}
        </span>
        <span>1</span>
      </div>
      <p className="prob-value">probability {formatProbability(probability)}</p>
    </div>
  )
}
