import { fileURLToPath, URL } from 'node:url';
import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls: { includeAbsolute: false } } })],
  base: '/static/app/',
  build: {
    outDir: fileURLToPath(new URL('../static/app', import.meta.url)),
    emptyOutDir: true,
    manifest: true,
    sourcemap: false,
    chunkSizeWarningLimit: 250,
  },
  server: {
    port: 18877,
    strictPort: true,
    proxy: Object.fromEntries(['/api', '/auth', '/admin', '/resource', '/static/css', '/static/js',
      '/static/vendor', '/static/icon', '/static/index.html', '/profile', '/login', '/favicon.ico']
      .map(path => [path, { target: process.env.PICMANAGER_API_URL || 'http://127.0.0.1:8777', changeOrigin: true }])),
  },
  test: { environment: 'happy-dom', include: ['tests/**/*.test.ts'], setupFiles: ['tests/setup.ts'], restoreMocks: true },
});
