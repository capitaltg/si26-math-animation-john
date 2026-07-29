import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import { developmentProxy } from './vite.proxy'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
  },
  server: {
    proxy: developmentProxy,
  },
})
