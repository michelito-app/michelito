// The installable app: a valid manifest with its icons, and a service worker that keeps the
// interface but never the data (/api) — neither in Cache Storage nor in IndexedDB.
import { expect, test } from '@playwright/test'

test.use({ serviceWorkers: 'allow' })

test('the manifest is valid and its icons are PNGs of the stated size', async ({ page }) => {
  await page.goto('/')
  const href = await page.locator('link[rel="manifest"]').getAttribute('href')
  expect(href).toBe('/manifest.webmanifest')
  const response = await page.request.get(href!)
  expect(response.ok()).toBe(true)
  expect(response.headers()['content-type']).toContain('application/manifest+json')
  const manifest = (await response.json()) as {
    name: string
    display: string
    start_url: string
    theme_color: string
    background_color: string
    icons: { src: string; sizes: string; type: string; purpose: string }[]
  }
  expect(manifest).toMatchObject({ name: 'Michelito', display: 'standalone', start_url: '/' })
  expect(manifest.theme_color).toMatch(/^#[0-9a-f]{6}$/i)
  expect(manifest.icons.map((icon) => icon.sizes)).toEqual(
    expect.arrayContaining(['192x192', '512x512']),
  )
  for (const icon of manifest.icons) {
    const image = await page.request.get(icon.src)
    expect(image.headers()['content-type']).toBe('image/png')
    const bytes = await image.body()
    const size = Number(icon.sizes.split('x')[0])
    expect(bytes.readUInt32BE(16)).toBe(size)
  }
  const apple = await page.locator('link[rel="apple-touch-icon"]').getAttribute('href')
  expect((await page.request.get(apple!)).headers()['content-type']).toBe('image/png')
  await expect(page.locator('meta[name="theme-color"]')).toHaveCount(2)
})

test('the service worker keeps the interface and never the data', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready
  })
  // Once it controls the page, use the data again (summary, transactions).
  await page.reload()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true)
  await page.evaluate(() => fetch('/api/months').then((r) => r.json()))
  await page.goto('/transactions')
  await expect(page.locator('[data-fingerprint]').first()).toBeVisible()

  const stored = await page.evaluate(async () => {
    const urls: string[] = []
    for (const name of await caches.keys()) {
      const cache = await caches.open(name)
      for (const request of await cache.keys()) urls.push(new URL(request.url).pathname)
    }
    const databases = 'databases' in indexedDB ? await indexedDB.databases() : []
    return { urls, databases: databases.map((db) => db.name) }
  })
  expect(stored.urls).toContain('/')
  expect(stored.urls.some((path) => path.startsWith('/assets/'))).toBe(true)
  expect(stored.urls.filter((path) => path.startsWith('/api'))).toEqual([])
  expect(stored.databases).toEqual([])
})
