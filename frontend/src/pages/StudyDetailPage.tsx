import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../api/client'
import type { PredictionOut, StudyStatus } from '../api/types'
import { StatusBadge } from '../components/Badges'
import { ErrorMessage } from '../components/ErrorMessage'
import { ResultPanel } from '../components/ResultPanel'
import { ScanViewer } from '../components/ScanViewer'
import { ShortUid, shortUid } from '../components/ShortUid'
import { useApiData } from '../hooks/useApiData'

export function StudyDetailPage() {
  const { id = '' } = useParams()
  // Status comes from the same listing the study list uses, rather than from parsing
  // the wording of a 404 message.
  const { state, reload } = useApiData((signal) => api.listStudies(signal), [id])

  let body
  if (state.status === 'loading') {
    body = <p role="status">Loading study{'…'}</p>
  } else if (state.status === 'error') {
    body = <ErrorMessage error={state.error} onRetry={reload} />
  } else {
    const study = state.data.studies.find((s) => s.orthanc_study_id === id)
    body = study ? (
      <StudyView key={study.orthanc_study_id} study={study} />
    ) : (
      <div className="notice-box">
        <p>No study with this ID is in Orthanc.</p>
      </div>
    )
  }

  return (
    <section aria-labelledby="detail-heading">
      <p>
        <Link to="/">Back to studies</Link>
      </p>
      <h1 id="detail-heading">Study</h1>
      {body}
    </section>
  )
}

function StudyView({ study }: { study: StudyStatus }) {
  if (study.status === 'not_synced') {
    return (
      <>
        <StudyHeader study={study} analysed={false} />
        <div className="notice-box">
          <p>
            This study is in Orthanc but has not been synced yet. Use Sync from Orthanc on
            the <Link to="/">study list</Link> first.
          </p>
        </div>
      </>
    )
  }
  return <SyncedStudy study={study} />
}

function StudyHeader({ study, analysed }: { study: StudyStatus; analysed: boolean }) {
  return (
    <div className="study-header">
      <ShortUid uid={study.study_instance_uid} />
      <StatusBadge status={analysed ? 'analysed' : study.status} />
    </div>
  )
}

function SyncedStudy({ study }: { study: StudyStatus }) {
  const id = study.orthanc_study_id
  const stored = useApiData(
    (signal) =>
      study.status === 'analysed' ? api.getResult(id, signal) : Promise.resolve(null),
    [id, study.status],
  )
  const [fresh, setFresh] = useState<PredictionOut | null>(null)
  const [analysing, setAnalysing] = useState(false)
  const [analyseError, setAnalyseError] = useState<unknown>(null)

  const result = fresh ?? (stored.state.status === 'ok' ? stored.state.data : null)

  async function analyse() {
    setAnalysing(true)
    setAnalyseError(null)
    try {
      setFresh(await api.analyse(id))
    } catch (err) {
      setAnalyseError(err)
    } finally {
      setAnalysing(false)
    }
  }

  return (
    <>
      <StudyHeader study={study} analysed={result !== null} />
      <div className="detail-grid">
        <ScanViewer orthancStudyId={id} shortUid={shortUid(study.study_instance_uid)} />
        <div>
          {stored.state.status === 'loading' ? (
            <p role="status">Loading result{'…'}</p>
          ) : stored.state.status === 'error' ? (
            <ErrorMessage error={stored.state.error} onRetry={stored.reload} />
          ) : result ? (
            <ResultPanel result={result} justAnalysed={fresh !== null} />
          ) : (
            <section className="panel" aria-labelledby="analyse-heading" aria-busy={analysing}>
              <h2 id="analyse-heading">Not analysed yet</h2>
              <p>
                Run the model and Grad-CAM on this study. The result is stored and every run
                is recorded in the audit log.
              </p>
              <button type="button" onClick={analyse} disabled={analysing}>
                {analysing ? 'Analysing…' : 'Analyse'}
              </button>
              <p role="status" className="muted">
                {analysing
                  ? 'Running the model and Grad-CAM on this study. This can take a few seconds.'
                  : ''}
              </p>
              {analyseError ? <ErrorMessage error={analyseError} onRetry={analyse} /> : null}
            </section>
          )}
        </div>
      </div>
    </>
  )
}
