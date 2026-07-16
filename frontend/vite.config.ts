import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        // ponytail: changeOrigin must stay false — the backend's trailing-slash 307s
        // build an absolute Location from the Host header. With changeOrigin:true the
        // Host becomes 127.0.0.1:8000, so the redirect escapes the proxy origin and the
        // httpOnly auth cookie (scoped to localhost:5173) is dropped → 401 → logout.
        changeOrigin: false,
        // Required for SSE: disable response buffering so events stream immediately
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
    },
  },
})
