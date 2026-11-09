import { api } from '../api/client'
import { useApiData, type LoadState } from '../hooks/useApiData'
import { ErrorMessage } from './ErrorMessage'

export const OVERLAY_CAPTION =
  'Highlights regions that influenced the pneumonia score. Not a diagnosis. It can also ' +
  'react to markers, borders and positioning.'
export const LOW_SCORE_CAPTION = 'Low score: the highlighted areas do not indicate findings.'
export const CAPTION_ID = 'gradcam-caption'

/**
 * GET /studies/{id}/heatmap for the shown prediction, only once the user has asked for it.
 *
 * The backend may have to recompute the overlay (after a restart or cache eviction), so it
 * is not fetched on page load; prediction_id is a dependency so a new prediction refetches.
 */
export function useHeatmap(
  orthancStudyId: string,
  predictionId: number,
  requested: boolean,
): { state: LoadState<Blob | null>; reload: () => void } {
  return useApiData(
    (signal) => (requested ? api.getHeatmap(orthancStudyId, signal) : Promise.resolve(null)),
    [orthancStudyId, predictionId, requested],
  )
}

/** The overlay image, drawn over the scan in the same frame. */
export function OverlayLayer({ url, opacity, shortUid }: { url: string; opacity: number; shortUid: string }) {
  return (
    <img
      className="overlay"
      src={url}
      alt={`Grad-CAM overlay for the study ending ${shortUid}: colour map over the scan`}
      aria-describedby={CAPTION_ID}
      style={{ opacity: opacity / 100 }}
    />
  )
}

/** Shown with the overlay whenever it is on; the extra sentence applies to label 0. */
export function OverlayCaption({ label }: { label: number }) {
  return (
    <p id={CAPTION_ID} className="overlay-caption">
      {OVERLAY_CAPTION}
      {label === 0 ? <> {LOW_SCORE_CAPTION}</> : null}
    </p>
  )
}

interface ControlsProps {
  on: boolean
  onToggle: (on: boolean) => void
  opacity: number
  onOpacity: (opacity: number) => void
  heatmap: LoadState<Blob | null>
  onRetry: () => void
}

/** Toggle (off by default, owned by the page) and opacity slider, both keyboard operable. */
export function OverlayControls({ on, onToggle, opacity, onOpacity, heatmap, onRetry }: ControlsProps) {
  return (
    <fieldset className="panel overlay-controls">
      <legend>Grad-CAM overlay</legend>
      <label className="check">
        <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} />
        Show Grad-CAM overlay
      </label>
      <div className="field">
        <label htmlFor="overlay-opacity">Overlay opacity</label>
        <div className="range-row">
          <input
            id="overlay-opacity"
            type="range"
            min={0}
            max={100}
            step={5}
            value={opacity}
            disabled={!on}
            aria-valuetext={`${opacity} percent`}
            onChange={(e) => onOpacity(Number(e.target.value))}
          />
          <output htmlFor="overlay-opacity">{opacity}%</output>
        </div>
      </div>
      {on && heatmap.status === 'loading' ? (
        <p role="status">Loading overlay{'…'}</p>
      ) : null}
      {on && heatmap.status === 'error' ? (
        <ErrorMessage error={heatmap.error} onRetry={onRetry} />
      ) : null}
    </fieldset>
  )
}
