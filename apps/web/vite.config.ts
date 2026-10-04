import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { env } from 'node:process';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/v1': { target: env.API_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } } },
  test: { environment: 'jsdom', setupFiles: './src/test-setup.ts' },
});
