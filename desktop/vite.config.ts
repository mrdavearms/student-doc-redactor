import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src http://127.0.0.1:8765; object-src 'none'; base-uri 'none'; frame-src 'none'"

// Build only: the dev server needs inline scripts for hot reload.
const contentSecurityPolicy = {
  name: 'content-security-policy',
  apply: 'build' as const,
  transformIndexHtml: () => [
    { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' as const },
  ],
}

export default defineConfig({
  plugins: [react(), tailwindcss(), contentSecurityPolicy],
  base: './',
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
  },
})
