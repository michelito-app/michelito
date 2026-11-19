import { defineConfig, devices } from '@playwright/test'

// E2E_PORT: another port if a test server (another copy of the repo) is already on 8598.
const PORT = Number(process.env.E2E_PORT ?? 8598)
// Household recurring charges and crypto income: their own server (the household flag of
// tests/e2e_server.py, which adds the household accounts and the P2P one) on the next port, so the
// figures the other specs expect don't change.
const HOUSEHOLD_PORT = PORT + 1
const HOUSEHOLD_SPECS = /(household|crypto)\.spec\.ts$/
// The public demo (`michelito demo`, tests/e2e_demo_server.py): its own server on PORT + 2.
const DEMO_PORT = PORT + 2
const DEMO_SPECS = /demo\.spec\.ts$/
// 8501 is the real board's port (`michelito board`): the tests never use it, not even for the
// second server.
const RESERVED_PORT = 8501
if ([PORT, HOUSEHOLD_PORT, DEMO_PORT].includes(RESERVED_PORT)) {
  throw new Error(
    `E2E_PORT=${PORT} would use port ${RESERVED_PORT} (the board's): pick another one (the tests use E2E_PORT, E2E_PORT+1 and E2E_PORT+2).`,
  )
}

// The test server (tests/e2e_server.py) serves the API and the built interface with made-up data
// in a temporary database. Run `npm run build` before `npm run e2e`.
export default defineConfig({
  testDir: 'e2e',
  // The server keeps a single database while it lives: the specs that edit data run serially.
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: [HOUSEHOLD_SPECS, DEMO_SPECS],
    },
    {
      name: 'household',
      use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${HOUSEHOLD_PORT}` },
      testMatch: HOUSEHOLD_SPECS,
    },
    {
      name: 'demo',
      use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${DEMO_PORT}` },
      testMatch: DEMO_SPECS,
    },
  ],
  webServer: [
    {
      command: `cd .. && uv run python -m tests.e2e_server --port ${PORT}`,
      url: `http://127.0.0.1:${PORT}/api/months`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `cd .. && uv run python -m tests.e2e_server --household --port ${HOUSEHOLD_PORT}`,
      url: `http://127.0.0.1:${HOUSEHOLD_PORT}/api/months`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `cd .. && uv run python -m tests.e2e_demo_server --port ${DEMO_PORT}`,
      url: `http://127.0.0.1:${DEMO_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
