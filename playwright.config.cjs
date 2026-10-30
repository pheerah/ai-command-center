process.env.PLAYWRIGHT_BROWSERS_PATH = require('node:path').resolve('.ai-team/browsers');
const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:3941', browserName: 'chromium' },
  webServer: {
    command: 'node scripts/e2e-server.js',
    url: 'http://127.0.0.1:3941/api/health',
    env: { PORT: '3941' },
    reuseExistingServer: false,
  },
});
