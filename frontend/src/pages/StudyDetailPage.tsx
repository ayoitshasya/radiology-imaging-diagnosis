import { Link } from 'react-router'

export function StudyDetailPage() {
  return (
    <section aria-labelledby="detail-heading">
      <p>
        <Link to="/">Back to studies</Link>
      </p>
      <h1 id="detail-heading">Study</h1>
      <p>The image, analysis result and Grad-CAM overlay are added in Part B.</p>
    </section>
  )
}
