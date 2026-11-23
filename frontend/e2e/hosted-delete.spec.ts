import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { codeIn, emailsTo, expireStepUp, invite, syntheticPdfs } from './hostedServer'
import { t } from './text'

// Hosted mode, deleting the account from Settings (tests/e2e_hosted_server.py). Desktop, phone
// and WebKit at an iPhone's size (projects `hosted`, `hosted-mobile` and `hosted-iphone`); each
// test uses its own made-up address, deleted for real on the throwaway e2e server.
const PDFS = syntheticPdfs()
const LANDING = t('auth.landing.title')

async function nextEmail(to: string, before: number) {
  await expect.poll(() => emailsTo(to).length, { timeout: 10_000 }).toBeGreaterThan(before)
  return emailsTo(to).at(-1)!
}

async function signInPastTheGate(page: Page, info: TestInfo, name: string): Promise<string> {
  const email = `${info.project.name}-delete-${name}-${Date.now()}@example.com`
  invite(email)
  await page.goto('/')
  await page.getByRole('button', { name: t('auth.landing.enter') }).click()
  await page.getByLabel(t('auth.signIn.email')).fill(email)
  await page.getByRole('button', { name: t('auth.signIn.sendCode') }).click()
  await page.getByLabel(t('auth.signIn.code')).fill(codeIn(await nextEmail(email, 0)))
  await page.getByRole('button', { name: t('auth.signIn.verify'), exact: true }).click()
  await page.locator('input[type="file"]').setInputFiles([PDFS['popular-card']])
  await page.getByRole('button', { name: t('onboarding.result.open') }).click()
  await expect(page.getByRole('navigation', { name: t('shell.nav.label') }).first()).toBeAttached()
  return email
}

async function openDeleteDialog(page: Page) {
  await page.goto('/settings')
  const zone = page.getByRole('region', { name: t('auth.delete.title') })
  await expect(zone).toBeVisible()
  await zone.getByRole('button', { name: t('auth.delete.open') }).click()
  const dialog = page.getByRole('dialog', { name: t('auth.delete.dialogTitle') })
  await expect(dialog).toBeVisible()
  return dialog
}

test('the danger zone explains the loss and waits for the account email', async ({ page }, info) => {
  const email = await signInPastTheGate(page, info, 'cancel')
  const dialog = await openDeleteDialog(page)
  for (const key of ['auth.delete.lossNow', 'auth.delete.lossBackups', 'auth.delete.lossGmail'] as const) {
    await expect(dialog.getByText(t(key))).toBeVisible()
  }
  const confirm = dialog.getByRole('button', { name: t('auth.delete.confirm') })
  const field = dialog.getByLabel(t('auth.delete.typeEmail', { email }))
  await expect(confirm).toBeDisabled()
  await field.fill('someone-else@example.com')
  await expect(confirm).toBeDisabled()
  await field.fill(email)
  await expect(confirm).toBeEnabled()

  await dialog.getByRole('button', { name: t('auth.delete.cancel') }).click()
  await expect(dialog).toHaveCount(0)
  expect((await page.request.get('/api/accounts')).status()).toBe(200)
})

test('deleting the account after a fresh code signs out with a notice', async ({ page }, info) => {
  const email = await signInPastTheGate(page, info, 'delete')
  expireStepUp(email)
  const dialog = await openDeleteDialog(page)
  await dialog.getByLabel(t('auth.delete.typeEmail', { email })).fill(email)
  await dialog.getByRole('button', { name: t('auth.delete.confirm') }).click()

  const sheet = page.getByRole('dialog', { name: t('auth.stepUp.title') })
  await expect(sheet).toBeVisible()
  const sent = emailsTo(email).length
  await sheet.getByRole('button', { name: t('auth.stepUp.send') }).click()
  await sheet.getByLabel(t('auth.signIn.code')).fill(codeIn(await nextEmail(email, sent)))
  await sheet.getByRole('button', { name: t('auth.stepUp.confirm') }).click()

  await expect(page.getByRole('heading', { name: LANDING })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: t('auth.delete.done') })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/')
  expect((await page.request.get('/api/accounts')).status()).toBe(401)
  // The notice shows once.
  await page.reload()
  await expect(page.getByRole('heading', { name: LANDING })).toBeVisible()
  await expect(page.getByText(t('auth.delete.done'))).toHaveCount(0)
})
