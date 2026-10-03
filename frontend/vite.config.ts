/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    exclude: ['e2e/**'],
  },
  server: {
    host: '0.0.0.0',
    port: 43123,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:43124',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      '/api-ws': {
        target: 'ws://127.0.0.1:43124',
        ws: true,
        rewrite: (p) => p.replace(/^\/api-ws/, ''),
      },
    },
  },
})
