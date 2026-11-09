import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <section aria-labelledby="notfound-heading">
      <h1 id="notfound-heading">Page not found</h1>
      <p>
        <Link to="/">Go to the study list</Link>
      </p>
    </section>
  )
}
