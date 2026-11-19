import { defineConfig, devices } from '@playwright/test'

// E2E_PORT: otro puerto si ya hay un servidor de pruebas (otra copia del repo) en 8598.
const PORT = Number(process.env.E2E_PORT ?? 8598)
// Recurrentes del hogar e ingresos de cripto: su propio servidor (`--hogar`, con las cuentas de la
// casa y la de P2P) en el puerto siguiente, para no cambiar las cifras que esperan las demás.
const HOGAR_PORT = PORT + 1
const HOGAR_SPECS = /(hogar|cripto)\.spec\.ts$/
// La demo pública (`finanzas demo`, tests/e2e_demo_server.py): su propio servidor en PORT + 2.
const DEMO_PORT = PORT + 2
const DEMO_SPECS = /demo\.spec\.ts$/
// 8501 es el del board de verdad (`finanzas board`): las pruebas nunca lo usan, ni para el
// segundo servidor.
const RESERVED_PORT = 8501
if ([PORT, HOGAR_PORT, DEMO_PORT].includes(RESERVED_PORT)) {
  throw new Error(
    `E2E_PORT=${PORT} usaría el puerto ${RESERVED_PORT} (el del board): elige otro (las pruebas usan E2E_PORT, E2E_PORT+1 y E2E_PORT+2).`,
  )
}

// El servidor de pruebas (tests/e2e_server.py) sirve la API y la interfaz compilada con datos
// inventados en una base temporal. Corre `npm run build` antes de `npm run e2e`.
export default defineConfig({
  testDir: 'e2e',
  // El servidor guarda una sola base mientras vive: las pruebas que corrigen datos van en serie.
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
      testIgnore: [HOGAR_SPECS, DEMO_SPECS],
    },
    {
      name: 'hogar',
      use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${HOGAR_PORT}` },
      testMatch: HOGAR_SPECS,
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
      command: `cd .. && uv run python -m tests.e2e_server --hogar --port ${HOGAR_PORT}`,
      url: `http://127.0.0.1:${HOGAR_PORT}/api/months`,
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
