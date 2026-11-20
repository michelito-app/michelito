import { expect, test } from '@playwright/test'
import { t } from './text'

// The local board (tests/e2e_server.py) knows nothing about hosted mode: no settings, no
// devices, no sign-in.
test('locally there is no sign-in, settings or devices', async ({ page }) => {
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: t('shell.nav.label') }).first()
  await expect(nav).toContainText(t('shell.localOnly'))
  await expect(nav.getByRole('link', { name: t('auth.shell.settings') })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: t('auth.landing.title') })).toHaveCount(0)
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: t('shell.notFound') })).toBeVisible()
  await expect(page.getByText(t('auth.devices.title'))).toHaveCount(0)
})
