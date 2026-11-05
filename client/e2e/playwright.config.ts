import { defineConfig } from '@playwright/test';

// Browser flows: the real viewer (`viewer.py --production`) on a seeded, model-free library,
// driven through the installed Chrome. Run with `npm run e2e` after `ng build`; see e2e/README.md.
const port = Number(process.env['FACET_E2E_PORT'] ?? 5099);
const python = process.env['FACET_E2E_PYTHON'] ?? 'python';

export default defineConfig({
  testDir: './flows',
  // One seeded library serves every flow; each flow owns its own folder in it, so they can run
  // in any order. One worker keeps the server's single-process writes simple.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env['CI'],
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: '../playwright-report' }]],
  outputDir: '../test-results',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // The installed Chrome (also preinstalled on GitHub's runners): no browser download.
    channel: process.env['FACET_E2E_CHANNEL'] ?? 'chrome',
    // The service worker stays ON: the thumbnail cache is where stale-picture bugs live.
    serviceWorkers: 'allow',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `${python} e2e/seed_library.py serve --port ${port}`,
    cwd: '..',
    url: `http://127.0.0.1:${port}/api/auth/status`,
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
