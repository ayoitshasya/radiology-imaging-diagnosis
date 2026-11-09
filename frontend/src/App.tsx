import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { AuditPage } from './pages/AuditPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { StudyDetailPage } from './pages/StudyDetailPage'
import { StudyListPage } from './pages/StudyListPage'

/** Routes only; the router itself is provided by main.tsx (or a MemoryRouter in tests). */
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<StudyListPage />} />
        <Route path="studies/:id" element={<StudyDetailPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
