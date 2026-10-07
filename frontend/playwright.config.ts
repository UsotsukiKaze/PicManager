import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:18877', viewport: { width: 1920, height: 1080 },
    headless: true, ...(process.env.PICMANAGER_BROWSER_CHANNEL ? { channel: process.env.PICMANAGER_BROWSER_CHANNEL } : {}),
    trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: { command: 'node tests/server.mjs', url: 'http://127.0.0.1:18877', reuseExistingServer: false },
});
