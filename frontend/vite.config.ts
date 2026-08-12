import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

/**
 * Fail the build when the backend URL is missing, rather than shipping a bundle that
 * requests `undefined/conversations`. Without this the deploy host builds green and
 * the app breaks only in the browser.
 */
function requireApiBaseUrl(mode: string): void {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
  if (!env.VITE_API_BASE_URL) {
    throw new Error('VITE_API_BASE_URL is not set — see frontend/.env.example')
  }
}

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  if (command === 'build') requireApiBaseUrl(mode)
  return {
    plugins: [react(), tailwindcss()],
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      // Tests stub fetch, but the client still builds absolute URLs from this.
      env: { VITE_API_BASE_URL: 'http://api.test' },
    },
  }
})
