import { defineConfig } from '@playwright/test';
import { EDITION_PASSWORD, PORT, PYTHON } from './env';

// Browser flows: the real viewer (`viewer.py --production`) on a seeded, model-free library,
// driven through the installed Chrome. Run with `npm run e2e` after `ng build`; see e2e/README.md.

export default defineConfig({
  testDir: './flows',
  // One seeded library serves every flow. Each flow owns its own folder, and a flow that changes
  // its folder resets it first, so the flows run in any order and repeat. One worker keeps the
  // server's single-process writes simple.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../playwright-report' }]],
  outputDir: '../test-results',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // The installed Chrome (also preinstalled on GitHub's runners): no browser download.
    channel: process.env['FACET_E2E_CHANNEL'] ?? 'chrome',
    // The service worker stays ON: the thumbnail cache is where stale-picture bugs live.
    serviceWorkers: 'allow',
    trace: 'retain-on-failure',
    // Off: recording needs Playwright's ffmpeg download, which the installed Chrome does not bring.
    video: 'off',
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `${PYTHON} e2e/seed_library.py serve --port ${PORT} --edition-password ${EDITION_PASSWORD}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/api/auth/status`,
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
