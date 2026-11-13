
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],

  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,

    allowedHosts: [
      'healthy-inns-harper-invitations.trycloudflare.com',
    ],

    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },

  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'https://healthy-inns-harper-invitations.trycloudflare.com',
      },
    },
    setupFiles: './tests/setup.ts',
    css: true,
  },
});
