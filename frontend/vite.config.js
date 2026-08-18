import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
      // ML-сервис живёт отдельно и может быть не запущен: тренажёр работает без него.
      '/ml': 'http://127.0.0.1:8100',
    },
  },
})
