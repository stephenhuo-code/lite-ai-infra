import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist' },
  server: {
    port: 5173,
    proxy: {
      // 同源(ADR-019):dev 让浏览器视角下 /auth /v1 与前端同源,带 BFF 会话 cookie、免 CORS
      '/auth': { target: 'http://localhost:8090', changeOrigin: false },
      '/v1': { target: 'http://localhost:8090', changeOrigin: false },
    },
  },
  test: { environment: 'jsdom', globals: true },
})
