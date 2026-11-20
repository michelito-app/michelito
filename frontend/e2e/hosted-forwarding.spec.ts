import { expect, test, type Page, type TestInfo } from '@playwright/test'
import {
  PDF_PASSWORD,
  codeIn,
  deliverEmail,
  emailsTo,
  expireStepUp,
  invite,
  syntheticPdfs,
} from './hostedServer'
import { t } from './text'

// Hosted mode, email forwarding (tests/e2e_hosted_server.py `deliver` plays the Email Worker with
// synthetic emails). Desktop and phone (projects `hosted` and `hosted-mobile`); each test uses its
// own made-up address.
const PDFS = syntheticPdfs()
const GMAIL_CODE = '123456789' // the made-up code of tests/forwarding_helpers.py

async function signInPastTheGate(page: Page, info: TestInfo, name: string): Promise<string> {
  const email = `${info.project.name}-forward-${name}-${Date.now()}@example.com`
  invite(email)
  await page.goto('/')
  await page.getByRole('button', { name: t('auth.landing.enter') }).click()
  await page.getByLabel(t('auth.signIn.email')).fill(email)
  await page.getByRole('button', { name: t('auth.signIn.sendCode') }).click()
  await expect.poll(() => emailsTo(email).length, { timeout: 10_000 }).toBeGreaterThan(0)
  await page.getByLabel(t('auth.signIn.code')).fill(codeIn(emailsTo(email).at(-1)!))
  await page.getByRole('button', { name: t('auth.signIn.verify'), exact: true }).click()
  await page.locator('input[type="file"]').setInputFiles([PDFS['popular-card']])
  await page.getByRole('button', { name: t('onboarding.result.open') }).click()
  await expect(page.getByRole('navigation', { name: t('shell.nav.label') }).first()).toBeAttached()
  return email
}

function automate(page: Page) {
  return page.locator('#automate')
}

async function address(page: Page): Promise<string> {
  const shown = automate(page).locator('[data-forwarding-address]')
  await expect(shown).toContainText('@michelito.app')
  return (await shown.textContent())!.trim()
}

/** Reload Settings until `check` passes (the statements are read in the background). */
async function settingsUntil(page: Page, check: () => Promise<void>) {
  await expect(async () => {
    await page.goto('/settings')
    await check()
  }).toPass({ timeout: 30_000 })
}

test('see the address, rotate it after a fresh verification and see Gmail’s code', async ({
  page,
}, info) => {
  const email = await signInPastTheGate(page, info, 'address')
  await page.goto('/settings')
  await expect(automate(page).getByRole('heading', { name: t('forwarding.title') })).toBeVisible()
  await automate(page).getByRole('button', { name: t('forwarding.address.create') }).click()
  const first = await address(page)
  expect(first).toMatch(/^[a-z]+\.[a-z2-7]{32}@michelito\.app$/)
  // Rotating needs a fresh verification: an email code, typed in the sheet.
  expireStepUp(email)
  const before = emailsTo(email).length
  await automate(page).getByRole('button', { name: t('forwarding.address.rotate') }).click()
  await page.getByRole('button', { name: t('auth.stepUp.send') }).click()
  await expect.poll(() => emailsTo(email).length, { timeout: 10_000 }).toBeGreaterThan(before)
  await page.getByLabel(t('auth.signIn.code')).fill(codeIn(emailsTo(email).at(-1)!))
  await page.getByRole('button', { name: t('auth.stepUp.confirm') }).click()
  await expect(automate(page).locator('[data-forwarding-address]')).not.toHaveText(first)
  const second = await address(page)
  // Gmail's confirmation arrives at the new address: its code is shown, never used by the app.
  deliverEmail(second, 'confirmation')
  await settingsUntil(page, async () => {
    const panel = page.getByRole('region', { name: t('forwarding.confirmation.title') })
    await expect(panel).toContainText(t('forwarding.confirmation.code', { code: GMAIL_CODE }))
  })
  await expect(page.locator('[data-confirmation-requester]')).toContainText('someone@example.com')
  // The guide: one screen, with the address and the banks' senders.
  await automate(page).getByRole('link', { name: t('forwarding.guide.link') }).click()
  await expect(page.getByRole('heading', { name: t('forwarding.guide.title') })).toBeVisible()
  await expect(page.locator('[data-forwarding-address]')).toHaveText(second)
  await expect(page.getByText('servicios@bhd.com.do')).toBeVisible()
})

test('a waiting statement opens with the typed password; quarantine is approved', async ({
  page,
}, info) => {
  await signInPastTheGate(page, info, 'inbox')
  await page.goto('/settings')
  await automate(page).getByRole('button', { name: t('forwarding.address.create') }).click()
  const to = await address(page)

  deliverEmail(to, 'locked')
  const waiting = page.getByRole('region', { name: t('forwarding.waiting.title') })
  await settingsUntil(page, async () => {
    await expect(waiting.locator('[data-waiting-reason="missing"]')).toHaveCount(1)
  })
  await expect(waiting).toContainText(t('forwarding.waiting.missing'))
  await waiting.getByLabel(t('forwarding.waiting.bank')).selectOption('bhd')
  await waiting.getByLabel(t('forwarding.waiting.password')).fill(PDF_PASSWORD)
  await waiting.getByRole('button', { name: t('forwarding.waiting.submit') }).click()
  await expect(page.getByRole('region', { name: t('forwarding.waiting.title') })).toHaveCount(0)
  // It squares, but it is an account this person does not have yet: it waits for approval,
  // after a second step that says what approving means.
  const held = page.getByRole('region', { name: t('forwarding.held.title') })
  await expect(held.locator('[data-held-item]')).toHaveCount(1)
  await held.getByRole('button', { name: t('forwarding.quarantine.approve') }).click()
  await expect(held.getByRole('alertdialog')).toContainText(t('forwarding.quarantine.otherCard'))
  await held.getByRole('button', { name: t('forwarding.quarantine.confirm') }).click()
  await expect(held).toHaveCount(0)

  deliverEmail(to, 'stranger')
  const quarantine = page.getByRole('region', { name: t('forwarding.quarantine.title') })
  await settingsUntil(page, async () => {
    await expect(quarantine.locator('[data-quarantine-item]')).toHaveCount(1)
  })
  await expect(quarantine).toContainText('unknown-sender.example')
  await expect(quarantine).toContainText(t('forwarding.quarantine.attachments', { count: 1 }))
  await quarantine.getByRole('button', { name: t('forwarding.quarantine.approve') }).click()
  await expect(quarantine.getByRole('alertdialog')).toContainText(
    t('forwarding.quarantine.confirmLead'),
  )
  await quarantine.getByRole('button', { name: t('forwarding.quarantine.confirm') }).click()
  await expect(quarantine).toHaveCount(0)
  // What entered by approval is listed, and can be taken back.
  const approvals = page.getByRole('region', { name: t('forwarding.approvals.title') })
  await expect(approvals.locator('[data-approval-item]')).toHaveCount(2) // the new account's statement and the unverified one
  await expect(approvals).toContainText('unknown-sender.example')

  // The statements card on the Summary: both forwarded statements arrived.
  await page.goto('/')
  const card = page.getByRole('region', { name: t('forwarding.card.title') })
  await expect(card).toBeVisible()
  await expect(card.getByRole('list').first().getByRole('listitem')).toHaveCount(2)
  await expect(card).toContainText('BHD')
  // The synthetic statements are from January: later ones are overdue, and the card says so.
  await expect(card.getByRole('list', { name: t('forwarding.card.attention') })).toBeVisible()
})
