import type { ReactNode } from 'react'
import { api } from '../api/client'
import { useApiData } from '../hooks/useApiData'
import { useObjectUrl } from '../hooks/useObjectUrl'
import { ErrorMessage } from './ErrorMessage'

interface Props {
  orthancStudyId: string
  shortUid: string
  /** Optional layer drawn exactly on top of the scan (same 224 x 224 frame). */
  overlay?: ReactNode
}

/** The preprocessed scan from GET /studies/{id}/image, fetched as bytes into memory. */
export function ScanViewer({ orthancStudyId, shortUid, overlay }: Props) {
  const { state, reload } = useApiData((signal) => api.getImage(orthancStudyId, signal), [
    orthancStudyId,
  ])
  const url = useObjectUrl(state.status === 'ok' ? state.data : null)

  return (
    <figure className="scan">
      {state.status === 'loading' ? <p role="status">Loading image{'…'}</p> : null}
      {state.status === 'error' ? <ErrorMessage error={state.error} onRetry={reload} /> : null}
      {url ? (
        <div className="scan-stack">
          <img
            src={url}
            alt={`Chest X-ray for the study ending ${shortUid}, preprocessed to 224 by 224 grayscale as the model sees it`}
          />
          {overlay}
        </div>
      ) : null}
      <figcaption className="muted">
        The image the model sees: the study's DICOM from Orthanc, resized to 224 by 224
        grayscale. Not a diagnostic-quality display.
      </figcaption>
    </figure>
  )
}
