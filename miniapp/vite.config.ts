import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: { resident: "index.html", admin: "admin/index.html" } } },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/max': 'http://localhost:8000',
    },
  },
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
