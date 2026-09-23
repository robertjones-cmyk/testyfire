import { defineConfig, devices } from '@playwright/test'

/**
 * Accessibility test run.
 *
 * Expects the backend (which also serves the built frontend) on 127.0.0.1:8000:
 *
 *     npm run build && python -m app run
 *     npm run test:a11y
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.TORCH_BASE_URL ?? 'http://127.0.0.1:8000',
    trace: 'retain-on-failure',
    // Use a pre-installed Chromium when one is provided (CI images often pin a
    // different build than this Playwright version would download).
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
      : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
