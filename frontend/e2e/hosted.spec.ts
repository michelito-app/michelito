import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { HOSTED_DEMO_URL, codeIn, emailsTo, expireStepUp, invite, syntheticPdfs } from './hostedServer'
import { literal, t } from './text'

// Hosted mode (tests/e2e_hosted_server.py): accounts by invitation, sign-in with a 6-digit code
// read from the server's outbox folder. Runs on desktop and on a phone (projects `hosted` and
// `hosted-mobile`); each test uses its own made-up address.
const LANDING = t('auth.landing.title')
const NAV = t('shell.nav.label')
// A new account sees the upload gate until one statement squares (hosted-gate.spec.ts).
const GATE = t('onboarding.gate.title')

function address(name: string, info: TestInfo): string {
  return `${info.project.name}-${name}-${Date.now()}@example.com`
}

/** The newest email to `to`, once there are more than `before`. */
async function nextEmail(to: string, before: number) {
  await expect.poll(() => emailsTo(to).length, { timeout: 10_000 }).toBeGreaterThan(before)
  return emailsTo(to).at(-1)!
}

async function askForCode(page: Page, email: string) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: LANDING })).toBeVisible()
  await page.getByRole('button', { name: t('auth.landing.enter') }).click()
  await page.getByLabel(t('auth.signIn.email')).fill(email)
  await page.getByRole('button', { name: t('auth.signIn.sendCode') }).click()
  await expect(page.getByText(literal(t('auth.signIn.sent', { email })))).toBeVisible()
}

async function typeCode(page: Page, code: string) {
  await page.getByLabel(t('auth.signIn.code')).fill(code)
  await page.getByRole('button', { name: t('auth.signIn.verify'), exact: true }).click()
}

/** Upload one synthetic statement through the API (the session's own database), so the gate
 * opens; then reload. */
async function openGate(page: Page) {
  const pdf = readFileSync(syntheticPdfs()['popular-card']).toString('base64')
  const started = await page.request.post('/api/uploads', {
    data: { files: [{ name: 'card.pdf', data: pdf }] },
    headers: { 'X-Michelito': '1' },
  })
  expect(started.status()).toBe(202)
  const { id } = (await started.json()) as { id: string }
  await expect
    .poll(async () => ((await (await page.request.get(`/api/uploads/${id}`)).json()) as { done: boolean }).done)
    .toBe(true)
  await page.reload()
  await expect(page.getByRole('navigation', { name: NAV }).first()).toBeAttached()
}

/** Invite, ask for a code and sign in (and, with `open`, get past the gate); returns the
 * address. */
async function signIn(page: Page, info: TestInfo, name: string, open = true): Promise<string> {
  const email = address(name, info)
  invite(email)
  await askForCode(page, email)
  // The invitation's code arrived seconds ago: no second email, and that code works.
  await typeCode(page, codeIn(await nextEmail(email, 0)))
  await expect(page.getByRole('heading', { name: GATE })).toBeVisible()
  if (open) await openGate(page)
  return email
}

async function openSettings(page: Page, info: TestInfo) {
  if (info.project.name === 'hosted-mobile') {
    await page.getByRole('button', { name: t('shell.nav.more'), exact: true }).click()
    await page.getByRole('dialog').getByRole('link', { name: t('auth.shell.settings') }).click()
  } else {
    await page.getByRole('link', { name: t('auth.shell.settings') }).click()
  }
  await expect(page.getByRole('heading', { name: t('auth.settings.title') })).toBeVisible()
}

test('without a session the API answers 401 and the landing shows', async ({ page, request }) => {
  expect((await request.get('/api/accounts')).status()).toBe(401)
  expect((await request.get('/api/summary')).status()).toBe(401)
  expect((await request.get('/api/health')).status()).toBe(200)
  const mode = await (await request.get('/api/mode')).json()
  expect(mode).toMatchObject({ mode: 'hosted', session: false })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: LANDING })).toBeVisible()
  await expect(page.getByRole('link', { name: t('auth.landing.demo') })).toHaveAttribute(
    'href',
    HOSTED_DEMO_URL,
  )
  await expect(page.getByRole('navigation', { name: NAV })).toHaveCount(0)
  await expect(page.getByText(t('shell.localOnly'))).toHaveCount(0)
})

test('signing in with the emailed code', async ({ page }, info) => {
  await signIn(page, info, 'code')
  await expect(page.getByText(t('auth.shell.signedIn')).first()).toBeAttached()
  expect((await page.request.get('/api/accounts')).status()).toBe(200)
})

test('the code field and a wrong code', async ({ page }, info) => {
  const email = address('wrong', info)
  invite(email)
  await askForCode(page, email)
  const field = page.getByLabel(t('auth.signIn.code'))
  await expect(field).toHaveAttribute('inputmode', 'numeric')
  await expect(field).toHaveAttribute('autocomplete', 'one-time-code')
  await expect(page.getByRole('button', { name: /\d+ s$/ })).toBeDisabled() // resend cooldown
  const code = codeIn(await nextEmail(email, 0))
  await typeCode(page, `${(Number(code) + 1) % 1_000_000}`.padStart(6, '0'))
  await expect(page.getByRole('alert')).toHaveText(literal('el código no es correcto')) // spanish-ui
  await typeCode(page, code)
  await expect(page.getByRole('heading', { name: GATE })).toBeVisible()
})

test('devices, and signing out everywhere asks for a fresh code', async ({
  page,
  browser,
}, info) => {
  const email = await signIn(page, info, 'devices')
  // A second device of the same account.
  const other = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
  })
  const second = await other.newPage()
  const before = emailsTo(email).length
  await askForCode(second, email)
  await typeCode(second, codeIn(await nextEmail(email, before)))
  await expect(second.getByRole('navigation', { name: NAV }).first()).toBeAttached()

  await openSettings(page, info)
  const lastSeen = t('auth.devices.lastSeen', { date: '' }).trim()
  await expect(page.getByRole('listitem').filter({ hasText: lastSeen })).toHaveCount(2)
  await expect(page.getByText(t('auth.devices.thisOne'), { exact: true })).toHaveCount(1)
  const firefox = t('auth.devices.label', { browser: 'Firefox', os: 'Windows' })
  await expect(page.getByText(firefox, { exact: true })).toBeVisible()

  expireStepUp(email)
  await page.getByRole('button', { name: t('auth.devices.signOutEverywhere') }).click()
  const sheet = page.getByRole('dialog', { name: t('auth.stepUp.title') })
  await expect(sheet).toBeVisible()
  const sent = emailsTo(email).length
  await sheet.getByRole('button', { name: t('auth.stepUp.send') }).click()
  const stepUp = await nextEmail(email, sent)
  expect(stepUp.text).not.toContain('#link=')
  await sheet.getByLabel(t('auth.signIn.code')).fill(codeIn(stepUp))
  await sheet.getByRole('button', { name: t('auth.stepUp.confirm') }).click()

  await expect(page.getByRole('heading', { name: LANDING })).toBeVisible()
  expect((await page.request.get('/api/accounts')).status()).toBe(401)
  expect((await second.request.get('/api/accounts')).status()).toBe(401)
  await other.close()
})

test('signing out on this device only', async ({ page }, info) => {
  await signIn(page, info, 'one')
  await openSettings(page, info)
  await page.getByRole('button', { name: t('auth.devices.signOut') }).click()
  await expect(page.getByRole('heading', { name: LANDING })).toBeVisible()
  expect((await page.request.get('/api/accounts')).status()).toBe(401)
})

test('the desktop link asks before signing in and leaves the address', async ({
  page,
  browser,
}, info) => {
  const email = await signIn(page, info, 'link', false)
  const desk = await (await browser.newContext()).newPage()
  const before = emailsTo(email).length
  await askForCode(desk, email)
  const sent = await nextEmail(email, before)
  const token = /#link=([A-Za-z0-9_-]+)/.exec(sent.text)?.[1]
  expect(token).toBeTruthy()
  const other = await (await browser.newContext()).newPage()
  await other.goto(`/#link=${token}`)
  const masked = `${email[0]}•••@example.com`
  const question = t('auth.link.confirm', { email: masked })
  await expect(other.getByRole('heading', { name: question })).toBeVisible()
  expect(new URL(other.url()).hash).toBe('')
  expect((await other.request.get('/api/accounts')).status()).toBe(401) // not used yet
  await other.getByRole('button', { name: t('auth.link.enter') }).click()
  await expect(other.getByRole('heading', { name: GATE })).toBeVisible()
  await other.context().close()
  await desk.context().close()
})
