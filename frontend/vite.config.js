import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/upload': 'http://localhost:8000',
      '/options': 'http://localhost:8000',
      '/storyboard': 'http://localhost:8000',
      '/render': 'http://localhost:8000',
      '/clips': 'http://localhost:8000',
      '/thumbnails': 'http://localhost:8000',
    },
  },
})
