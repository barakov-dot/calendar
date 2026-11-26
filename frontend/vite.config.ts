import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    // В проде /api проксирует Caddy, в разработке — Vite.
    proxy: { '/api': 'http://api:8000' },
  },
})
