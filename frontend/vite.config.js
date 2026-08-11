import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import { developmentProxy } from './vite.proxy'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.js'],
    exclude: ['node_modules/**', 'e2e/**'],
  },
  server: {
    proxy: developmentProxy,
  },
})
