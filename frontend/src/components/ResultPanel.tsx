import type { PredictionOut } from '../api/types'
import { formatDateTime, formatLabel, formatProbability, formatThreshold } from '../format'
import { ProbabilityBar } from './ProbabilityBar'

/** First 12 hex characters: enough to tell checkpoints apart; the full hash is in the title. */
export function shortHash(sha256: string): string {
  return sha256.slice(0, 12)
}

interface Props {
  result: PredictionOut
  /** True right after POST analyse; then `cached` means no new analysis was run. */
  justAnalysed: boolean
}

/** Everything the API returned about the prediction, shown as text next to the bar. */
export function ResultPanel({ result, justAnalysed }: Props) {
  return (
    <section className="panel" aria-labelledby="result-heading">
      <h2 id="result-heading">Model output</h2>
      {justAnalysed && result.cached ? (
        <p className="muted">
          This study already had a result, so the stored one was returned and no new
          analysis was run.
        </p>
      ) : null}
      <ProbabilityBar probability={result.probability} threshold={result.threshold} />
      <dl className="facts">
        <dt>Probability</dt>
        <dd>{formatProbability(result.probability)}</dd>
        <dt>Decision threshold</dt>
        <dd>
          {formatThreshold(result.threshold)}
          {result.threshold_source ? (
            <span className="muted"> (chosen on the {result.threshold_source})</span>
          ) : null}
        </dd>
        <dt>Label at threshold</dt>
        <dd>{formatLabel(result.label, result.threshold)}</dd>
        {result.label_meaning ? (
          <>
            <dt>What the label means</dt>
            <dd>{result.label_meaning}</dd>
          </>
        ) : null}
        <dt>Model</dt>
        <dd>{result.model_name}</dd>
        <dt>Checkpoint (SHA-256, first 12)</dt>
        <dd>
          <code title={result.checkpoint_sha256}>{shortHash(result.checkpoint_sha256)}</code>
        </dd>
        <dt>Analysed at</dt>
        <dd>{formatDateTime(result.created_at)}</dd>
        {result.prediction_count !== undefined ? (
          <>
            <dt>Predictions stored for this study</dt>
            <dd>{result.prediction_count} (the latest is shown)</dd>
          </>
        ) : null}
      </dl>
    </section>
  )
}
