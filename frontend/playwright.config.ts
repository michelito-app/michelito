import { defineConfig, devices } from '@playwright/test'
import { HOSTED_DEMO_PORT, HOSTED_DIR, HOSTED_PORT } from './e2e/hostedServer'

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
// Hosted mode (tests/e2e_hosted_server.py, accounts and email sign-in with an outbox folder): its
// own server outside the e2e range of the others (E2E_HOSTED_PORT, 8636 by default).
// The gate's demo exit: a demo of its own on E2E_HOSTED_PORT + 1 that links back to it.
const HOSTED_SPECS = /hosted(-gate)?\.spec\.ts$/
// The phone layout and the installable app: the main server, with a phone viewport and touch.
const MOBILE_SPECS = /(mobile|pwa)\.spec\.ts$/
const PHONE = { ...devices['Desktop Chrome'], isMobile: true, hasTouch: true }
// Shared is mobile-first: its spec runs on the desktop project and at both phone widths too.
const SHARED_SPECS = /shared\.spec\.ts$/
// Live sync (provisional transactions from bank alerts): its own server, with made-up
// provisionals and test-only routes (tests/e2e_live.py), so the other specs' figures stay the
// same. Desktop and phone; ports from 8640 (8598-8600 and 8636 are taken).
const LIVE_PORT = Number(process.env.E2E_LIVE_PORT ?? 8640)
const LIVE_SPECS = /live\.spec\.ts$/
// 8501 is the real board's port (`michelito board`): the tests never use it, not even for the
// second server.
const RESERVED_PORT = 8501
if (
  [PORT, HOUSEHOLD_PORT, DEMO_PORT, HOSTED_PORT, HOSTED_DEMO_PORT, LIVE_PORT].includes(
    RESERVED_PORT,
  )
) {
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
    // The app's service worker (only in pwa.spec.ts) would stand between the page and page.route.
    serviceWorkers: 'block',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: [HOUSEHOLD_SPECS, DEMO_SPECS, MOBILE_SPECS, HOSTED_SPECS, LIVE_SPECS],
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
    {
      name: 'mobile',
      use: { ...PHONE, viewport: { width: 390, height: 844 } },
      testMatch: [MOBILE_SPECS, SHARED_SPECS],
    },
    {
      name: 'hosted',
      use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${HOSTED_PORT}` },
      testMatch: HOSTED_SPECS,
    },
    {
      name: 'hosted-mobile',
      use: {
        ...PHONE,
        viewport: { width: 390, height: 844 },
        baseURL: `http://127.0.0.1:${HOSTED_PORT}`,
      },
      testMatch: HOSTED_SPECS,
    },
    {
      name: 'mobile-360',
      use: { ...PHONE, viewport: { width: 360, height: 740 } },
      testMatch: [/mobile\.spec\.ts$/, SHARED_SPECS],
    },
    {
      name: 'live',
      use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${LIVE_PORT}` },
      testMatch: LIVE_SPECS,
    },
    {
      name: 'live-mobile',
      use: { ...PHONE, viewport: { width: 390, height: 844 }, baseURL: `http://127.0.0.1:${LIVE_PORT}` },
      testMatch: LIVE_SPECS,
      // The same server and database as `live` (each test resets it; the suite runs serially).
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
      command: `cd .. && uv run python -m tests.e2e_server --live --port ${LIVE_PORT}`,
      url: `http://127.0.0.1:${LIVE_PORT}/api/months`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `cd .. && uv run python -m tests.e2e_demo_server --port ${DEMO_PORT}`,
      url: `http://127.0.0.1:${DEMO_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `cd .. && uv run python -m tests.e2e_demo_server --port ${HOSTED_DEMO_PORT} --return-url http://127.0.0.1:${HOSTED_PORT}/`,
      url: `http://127.0.0.1:${HOSTED_DEMO_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `cd .. && uv run python -m tests.e2e_hosted_server --port ${HOSTED_PORT} --dir ${HOSTED_DIR} --demo-url http://127.0.0.1:${HOSTED_DEMO_PORT}`,
      url: `http://127.0.0.1:${HOSTED_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
