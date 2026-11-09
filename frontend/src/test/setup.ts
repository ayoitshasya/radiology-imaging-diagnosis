import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom has no object URLs; the viewer only needs a string to put in <img src>.
if (!('createObjectURL' in URL)) {
  Object.assign(URL, {
    createObjectURL: () => 'blob:test-image',
    revokeObjectURL: () => undefined,
  })
}

afterEach(() => {
  cleanup()
})
