import { NavLink, Outlet } from 'react-router'
import { Banner } from './Banner'

export function Layout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <Banner />
      <header className="site-header">
        <p className="site-title">Radiology review viewer</p>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Studies
          </NavLink>
          <NavLink to="/audit">Audit log</NavLink>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
    </>
  )
}
