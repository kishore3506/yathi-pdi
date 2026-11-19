import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const releaseId = process.env.VITE_APP_VERSION || Date.now().toString(36)

const versionedServiceWorker = {
  name: 'versioned-pdi-service-worker',
  closeBundle() {
    const workerPath = resolve(process.cwd(), 'dist/sw.js')
    const worker = readFileSync(workerPath, 'utf8')
    writeFileSync(
      workerPath,
      worker.replace('__PDI_RELEASE_ID__', releaseId),
      'utf8',
    )
  },
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), versionedServiceWorker],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000'
      }
    }
  }
})
