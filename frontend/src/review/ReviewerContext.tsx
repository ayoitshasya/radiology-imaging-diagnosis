import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

interface ReviewerState {
  reviewer: string
  setReviewer: (name: string) => void
}

const ReviewerContext = createContext<ReviewerState | null>(null)

/**
 * Remembers the reviewer name for this browser session only. It lives in React state at the
 * top of the app, so it is shared across studies but never written to localStorage,
 * sessionStorage or cookies, and is gone after a reload.
 */
export function ReviewerProvider({ children }: { children: ReactNode }) {
  const [reviewer, setReviewer] = useState('')
  const value = useMemo(() => ({ reviewer, setReviewer }), [reviewer])
  return <ReviewerContext.Provider value={value}>{children}</ReviewerContext.Provider>
}

export function useReviewer(): ReviewerState {
  const state = useContext(ReviewerContext)
  if (!state) throw new Error('useReviewer must be used inside ReviewerProvider')
  return state
}
