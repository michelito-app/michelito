import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { readFileSync } from 'node:fs'
import {
  HOSTED_DEMO_URL,
  PDF_PASSWORD,
  codeIn,
  emailsTo,
  invite,
  syntheticPdfs,
} from './hostedServer'
import { literal, t } from './text'

// Hosted mode, the gate and onboarding (tests/e2e_hosted_server.py, synthetic statements from
// tests/synthetic_pdf.py). Runs on desktop and on a phone (projects `hosted` and
// `hosted-mobile`); each test uses its own made-up address.
const GATE = t('onboarding.gate.title')
const NAV = t('shell.nav.label')
const PDFS = syntheticPdfs()

function address(name: string, info: TestInfo): string {
  return `${info.project.name}-gate-${name}-${Date.now()}@example.com`
}

/** Invite and sign in with the emailed code: a new account lands on the gate. */
async function signIn(page: Page, info: TestInfo, name: string): Promise<string> {
  const email = address(name, info)
  invite(email)
  await page.goto('/')
  await page.getByRole('button', { name: t('auth.landing.enter') }).click()
  await page.getByLabel(t('auth.signIn.email')).fill(email)
  await page.getByRole('button', { name: t('auth.signIn.sendCode') }).click()
  await expect.poll(() => emailsTo(email).length, { timeout: 10_000 }).toBeGreaterThan(0)
  await page.getByLabel(t('auth.signIn.code')).fill(codeIn(emailsTo(email).at(-1)!))
  await page.getByRole('button', { name: t('auth.signIn.verify'), exact: true }).click()
  await expect(page.getByRole('heading', { name: GATE })).toBeVisible()
  return email
}

async function choose(page: Page, ...names: (keyof typeof PDFS)[]) {
  await page.locator('input[type="file"]').setInputFiles(names.map((name) => PDFS[name]))
}

function row(page: Page, name: string) {
  return page.getByRole('listitem').filter({ hasText: `${name}.pdf` })
}

async function expectState(page: Page, name: string, state: string) {
  await expect(row(page, name)).toHaveAttribute('data-file-state', state)
}

async function expectNoShell(page: Page) {
  await expect(page.getByRole('navigation', { name: NAV })).toHaveCount(0)
  await expect(page.locator('[data-bottom-bar]')).toHaveCount(0)
}

test('no app shell before the first squared statement, whatever the address', async ({
  page,
}, info) => {
  await signIn(page, info, 'shell')
  await expectNoShell(page)
  await expect(page.getByText(t('onboarding.gate.trust'))).toBeVisible()
  for (const path of ['/transactions', '/settings', '/budget?month=2026-01']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: GATE })).toBeVisible()
    await expectNoShell(page)
    await expect.poll(() => new URL(page.url()).pathname).toBe('/')
  }
})

test('nothing squares: per-file reasons, the gate stays closed, retry and the demo', async ({
  page,
}, info) => {
  await signIn(page, info, 'none')
  await choose(page, 'wrong-total', 'other-bank')
  await expectState(page, 'wrong-total', 'invalid')
  await expectState(page, 'other-bank', 'unsupported')
  await expect(row(page, 'wrong-total')).toContainText(t('onboarding.file.invalid'))
  await expect(row(page, 'other-bank')).toContainText(t('onboarding.file.unsupported'))
  const none = page.getByRole('status').filter({ hasText: t('onboarding.result.none') })
  await expect(none).toBeVisible()
  await expect(none.getByRole('button', { name: t('onboarding.result.retry') })).toBeVisible()
  await expect(none.getByRole('link', { name: t('onboarding.gate.demo') })).toHaveAttribute(
    'href',
    HOSTED_DEMO_URL,
  )
  await expect(page.getByRole('button', { name: t('onboarding.result.open') })).toHaveCount(0)
  // "Notify me when it is supported": only a bank from the list.
  await row(page, 'other-bank').getByRole('button', { name: t('onboarding.request.open') }).click()
  await row(page, 'other-bank').getByLabel(t('onboarding.request.which')).selectOption('scotiabank')
  await row(page, 'other-bank').getByRole('button', { name: t('onboarding.request.send') }).click()
  await expect(row(page, 'other-bank')).toContainText(t('onboarding.request.done'))
  await page.reload()
  await expect(page.getByRole('heading', { name: GATE })).toBeVisible()
  await expectNoShell(page)
})

test('a locked statement asks for its bank password again when wrong, then the gate opens', async ({
  page,
}, info) => {
  await signIn(page, info, 'open')
  await choose(page, 'bhd-card', 'popular-card', 'wrong-total')
  await expectState(page, 'popular-card', 'squared')
  await expect(row(page, 'popular-card')).toContainText(
    literal('Popular · Tarjeta ···1234 · enero 2026 · 4 transacciones'), // spanish-ui
  )
  await expect(row(page, 'popular-card')).toContainText(t('onboarding.file.squared'))
  await expectState(page, 'bhd-card', 'locked')
  await expectState(page, 'wrong-total', 'invalid')
  // «Ver mi resumen» is there as soon as one squares; the password can still be given.
  await expect(page.getByRole('button', { name: t('onboarding.result.open') })).toBeVisible()
  const prompt = page.getByRole('region', { name: t('onboarding.password.title') })
  await prompt.getByLabel(t('onboarding.password.bank')).selectOption('bhd')
  await prompt.getByLabel(t('onboarding.password.field')).fill('not-the-password')
  await prompt.getByRole('button', { name: t('onboarding.password.submit') }).click()
  await expect(prompt.getByRole('alert')).toHaveText(t('onboarding.password.wrong', { bank: 'BHD' }))
  await expectState(page, 'bhd-card', 'locked')
  await prompt.getByLabel(t('onboarding.password.field')).fill(PDF_PASSWORD)
  await prompt.getByRole('button', { name: t('onboarding.password.submit') }).click()
  await expectState(page, 'bhd-card', 'squared')
  await expect(prompt).toHaveCount(0)

  await page.getByRole('button', { name: t('onboarding.result.open') }).click()
  await expect(page.getByRole('navigation', { name: NAV }).first()).toBeAttached()
  await expect.poll(() => new URL(page.url()).searchParams.get('month')).toBe('2026-01')
  // The first review and the checklist, on top of the first Summary.
  const review = page.getByRole('region', { name: t('onboarding.review.title') })
  await expect(review).toBeVisible()
  const checklist = page.getByRole('region', { name: t('onboarding.checklist.title') })
  await expect(checklist).toContainText(t('onboarding.checklist.months'))
  await expect(checklist).toContainText(t('onboarding.checklist.soon'))
  await review.getByRole('button', { name: t('onboarding.review.correct') }).first().click()
  await expect(review.getByText(t('onboarding.review.reviewed')).first()).toBeVisible()
  await review.getByRole('button', { name: t('onboarding.review.later') }).click()
  await expect(review).toHaveCount(0)
  await checklist.getByRole('button', { name: t('onboarding.checklist.dismiss') }).click()
  await expect(checklist).toHaveCount(0)
  // No tooltip tour anywhere.
  await expect(page.getByRole('tooltip')).toHaveCount(0)
})

test('the sample data is a separate session with its band, and the way back', async ({
  page,
}, info) => {
  await signIn(page, info, 'demo')
  await page.getByRole('link', { name: t('onboarding.gate.demo') }).first().click()
  await expect.poll(() => page.url()).toContain(HOSTED_DEMO_URL)
  const band = page.getByRole('region', { name: t('onboarding.band.label') })
  await expect(band).toBeVisible()
  await expect(band).toContainText(t('onboarding.band.text'))
  const box = await band.boundingBox()
  expect(box?.y).toBe(0) // on top, on the phone too
  await page.goto(`${HOSTED_DEMO_URL}/transactions`)
  await expect(band).toBeVisible()
  // The band depends on the demo server's mode, which says where to go back.
  const demoMode = await (await page.request.get(`${HOSTED_DEMO_URL}/api/mode`)).json()
  expect(demoMode).toMatchObject({ mode: 'demo' })
  expect(demoMode.return_url).toContain('127.0.0.1')
  const demoAccounts = await (await page.request.get(`${HOSTED_DEMO_URL}/api/accounts`)).json()
  expect(demoAccounts.length).toBeGreaterThan(0)
  await band.getByRole('link', { name: t('onboarding.band.back') }).click()
  await expect(page.getByRole('heading', { name: GATE })).toBeVisible()
  // The user's own data was never touched: still gated, no accounts.
  const accounts = await page.request.get('/api/accounts')
  expect(accounts.status()).toBe(403) // the server keeps the gate closed too
  expect(accounts.headers()['x-michelito-error']).toBe('gate_closed')
  expect(await (await page.request.get('/api/onboarding')).json()).toMatchObject({ open: false })
})

test('with one statement every main view shows data, a suggestion or a designed empty state', async ({
  page,
}, info) => {
  await signIn(page, info, 'views')
  await choose(page, 'popular-card')
  await expectState(page, 'popular-card', 'squared')
  await page.getByRole('button', { name: t('onboarding.result.open') }).click()
  await expect(page.getByRole('navigation', { name: NAV }).first()).toBeAttached()
  const generic = [
    t('pending.empty'),
    t('investments.empty'),
    t('recurring.empty.title'),
    t('reports.page.empty'),
    t('log.empty.title'),
    t('budget.noStatements'),
  ]
  const designed = ['/pending', '/investments', '/recurring', '/log']
  const withData = ['/', '/transactions', '/budget', '/reports', '/accounts', '/categories', '/import']
  for (const path of [...withData, ...designed]) {
    await page.goto(path)
    const main = page.locator('main')
    await expect(main.locator('h1, h2').first()).toBeVisible()
    for (const text of generic) await expect(main.getByText(text, { exact: true })).toHaveCount(0)
    if (designed.includes(path)) {
      const empty = main.locator('[data-empty-state], [data-suggestion]').first()
      await expect(empty, path).toBeVisible()
      await expect(empty.locator('h2')).not.toBeEmpty()
      await expect(empty.locator('p').first()).not.toBeEmpty()
      await expect(empty.getByRole('link').first()).toBeVisible()
    } else {
      await expect(main.locator('[data-empty-state]'), path).toHaveCount(0)
    }
  }
  // "See how it looks" opens that view in the demo.
  await page.goto('/recurring')
  await expect(page.getByRole('link', { name: t('onboarding.empty.preview') })).toHaveAttribute(
    'href',
    `${HOSTED_DEMO_URL}/recurring`,
  )
  await expect(page.getByText(t('onboarding.empty.recurring.title'))).toBeVisible()
  // Importing statements after the gate: in the menu (in "More" on the phone).
  await page.goto('/')
  if (info.project.name === 'hosted-mobile') {
    await page.getByRole('button', { name: t('shell.nav.more') }).click()
    await page.getByRole('dialog').getByRole('link', { name: t('shell.nav.import') }).click()
  } else {
    await page.getByRole('link', { name: t('shell.nav.import') }).click()
  }
  await expect(page.getByRole('heading', { name: t('onboarding.upload.title') })).toBeVisible()
  await choose(page, 'popular-card')
  await expectState(page, 'popular-card', 'duplicate')
})

test('a PDF shared to the app waits for an explicit Import', async ({ page }, info) => {
  await signIn(page, info, 'share')
  // What Android's share sheet posts (same browser: its cookie jar keeps the share cookie).
  const shared = await page.request.post('/share-target', {
    multipart: {
      statements: {
        name: 'shared-card.pdf',
        mimeType: 'application/pdf',
        buffer: readFileSync(PDFS['popular-card']),
      },
    },
    headers: { 'Sec-Fetch-Site': 'none' }, // a browser-initiated navigation, like the OS sheet
    maxRedirects: 0,
  })
  expect(shared.status()).toBe(303)
  await page.goto(shared.headers()['location'])
  const prompt = page.getByRole('region', { name: t('onboarding.share.title', { count: 1 }) })
  await expect(prompt).toContainText('shared-card.pdf')
  expect(new URL(page.url()).hash).toBe('') // the token left the address
  await expect(page.locator('[data-file-state]')).toHaveCount(0) // nothing imported yet
  expect(await (await page.request.get('/api/uploads/latest')).json()).toBeNull()
  await prompt.getByRole('button', { name: t('onboarding.share.import') }).click()
  await expectState(page, 'shared-card', 'squared')
  await expect(page.getByRole('button', { name: t('onboarding.result.open') })).toBeVisible()
})
