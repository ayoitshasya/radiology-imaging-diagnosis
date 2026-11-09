import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  // Pinned to the one origin the backend's CORS setting allows.
  server: { host: 'localhost', port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
    // Tests never reach a real server; fetch is mocked and this base is only used in URLs.
    env: { VITE_API_BASE_URL: 'http://api.test' },
  },
})
