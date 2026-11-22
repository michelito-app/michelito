// A new shared group from a credit ("It is a payment…" → "+ New group"), on a wide screen and on
// the phone (chromium, mobile, iphone, mobile-360). Made-up data from tests/e2e_server.py: the
// RD$ 500 «TOKE DE AMIGA INVENTADA» pays back part of the RD$ 3,000 shared dinner, and the
// RD$ 1,000 «TOKE DE PERSONA FICTICIA» is another payment of the same dinner. The test undoes
// everything at the end through the log.
import { expect, test, type Page } from '@playwright/test'
import { fingerprintOf, logMark, undoSince } from './ledger'
import { literal, t } from './text'
import type { Group, SharedHome } from '../src/lib/sharedApi'

const FEBRUARY = '2026-02'
const GROUP = 'Cena con amigas de prueba' // spanish-data
const PHONE_WIDTH = 768

let mark = 0
test.beforeEach(async ({ request }) => {
  mark = await logMark(request)
})
test.afterEach(async ({ request }) => {
  await undoSince(request, mark)
})

function isPhone(page: Page): boolean {
  return page.viewportSize()!.width < PHONE_WIDTH
}

/** Opens the credit's payment sheet: in the "More" list on a phone, in the panel elsewhere. */
async function openCreditSheet(page: Page, fingerprint: string) {
  await page.goto(`/transactions?month=${FEBRUARY}&tx=${fingerprint}`)
  if (isPhone(page)) {
    await page
      .locator('[data-mobile-detail]')
      .getByRole('region', { name: t('transactions.actions.more') })
      .getByRole('button', { name: t('shared.credit.title') })
      .click()
  } else {
    await page
      .getByRole('complementary')
      .getByRole('region', { name: t('shared.credit.title') })
      .getByRole('button', { name: t('shared.tx.record') })
      .click()
  }
  return page.getByRole('dialog', { name: t('shared.credit.title') })
}

test('a credit starts a new group with the expense it pays back and another payment, in one undo', async ({
  page,
}) => {
  const amiga = await fingerprintOf(page.request, FEBRUARY, /TOKE DE AMIGA INVENTADA/)
  const sheet = await openCreditSheet(page, amiga)
  await sheet.getByRole('button', { name: t('shared.credit.newGroup') }).click()

  const flow = page.getByRole('dialog', { name: t('shared.credit.newTitle') })
  const next = flow.getByRole('button', { name: t('shared.credit.next') })
  // 1. Who paid: taken from the transfer (a new person named as the bank prints it).
  await expect(flow.getByText(t('shared.credit.step', { n: 1, total: 4 }))).toBeVisible()
  await expect(flow.getByRole('list', { name: t('shared.newGroup.people') })).toContainText(
    'Amiga Inventada', // spanish-data
  )
  if (isPhone(page)) {
    // The sheet takes the whole screen and the main button stays within reach.
    const box = (await flow.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(page.viewportSize()!.height - 1)
    await expect(next).toBeInViewport()
  }
  await next.click()

  // 2. The expense: the dinner fits (RD$ 500 is a sixth of it); search by amount finds it.
  const dinner = flow.getByRole('checkbox', { name: /RESTAURANTE COMPARTIDO/ })
  await expect(dinner).toHaveAccessibleName(new RegExp(`RESTAURANTE COMPARTIDO.*${t('shared.credit.fits')}`))
  // Checking a row far down the list does not scroll the whole dialog (its header stays).
  const boxes = flow.getByRole('list', { name: t('shared.credit.expense') }).getByRole('checkbox')
  await boxes.last().check({ force: true })
  expect(await flow.evaluate((d) => d.scrollTop)).toBe(0)
  await boxes.last().uncheck({ force: true })
  await flow.getByPlaceholder(t('shared.credit.search')).fill('3,000')
  await expect(dinner).toBeVisible()
  await dinner.check({ force: true })
  await expect(dinner).toBeChecked()
  await expect(next).toBeEnabled()
  await next.click()

  // 3. Another payment of the same group, from someone else.
  const other = flow.getByRole('checkbox', { name: /TOKE DE PERSONA FICTICIA/ })
  await expect(flow.getByRole('button', { name: t('shared.credit.skip') })).toBeVisible()
  await other.check({ force: true })
  const who = flow.getByRole('group', { name: t('shared.credit.fromWho') })
  await expect(who.getByRole('button', { name: 'Persona Ficticia' })).toHaveAttribute('aria-pressed', 'true') // spanish-data
  await next.click()

  // 4. Name and split: their share is what they paid (RD$ 1,500 of RD$ 3,000), so it is settled.
  const name = flow.getByLabel(t('shared.credit.name'))
  await expect(name).toHaveValue(/RESTAURANTE COMPARTIDO/)
  await name.fill(GROUP)
  const paid = flow.getByRole('radio', { name: new RegExp(t('shared.credit.splitPaid')) })
  await expect(paid).toBeChecked()
  await expect(flow).toContainText(t('shared.credit.splitPaidHint', { mine: 'RD$ 1,500' }))
  await flow.getByRole('button', { name: t('shared.credit.create') }).click()
  await expect(flow).toHaveCount(0)

  // One change in the log; the group has both people, settled.
  const log = (await (await page.request.get('/api/log?limit=20')).json()) as { items: { id: number }[] }
  expect(log.items.filter((e) => e.id > mark)).toHaveLength(1)
  const home = (await (await page.request.get('/api/shared')).json()) as SharedHome
  const made = home.groups.find((g) => g.name === GROUP)!
  const group = (await (await page.request.get(`/api/shared/groups/${made.id}`)).json()) as Group
  expect(group.members.map((m) => m.name)).toEqual(['me', 'Amiga Inventada', 'Persona Ficticia']) // spanish-data
  expect(group.members.every((m) => m.balance.length === 0)).toBe(true)
  expect(group.timeline.map((i) => i.kind).sort()).toEqual(['entry', 'payment', 'payment'])

  // The credit now shows its group in the detail.
  await page.reload()
  if (isPhone(page)) {
    await expect(page.locator('[data-mobile-detail]')).toContainText(t('shared.tx.payment', { group: GROUP }))
  } else {
    await expect(
      page.getByRole('complementary').getByRole('link', { name: literal(t('shared.tx.openGroup')) }),
    ).toBeVisible()
  }
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})

test('a cash expense and equal parts leave what is still owed', async ({ page }) => {
  const amiga = await fingerprintOf(page.request, FEBRUARY, /TOKE DE AMIGA INVENTADA/)
  const sheet = await openCreditSheet(page, amiga)
  await sheet.getByRole('button', { name: t('shared.credit.newGroup') }).click()
  const flow = page.getByRole('dialog', { name: t('shared.credit.newTitle') })
  const next = flow.getByRole('button', { name: t('shared.credit.next') })
  await next.click()

  await flow.getByRole('button', { name: t('shared.credit.cash') }).click()
  await flow.getByLabel(t('shared.credit.cashDescription')).fill('Taxi de prueba') // spanish-data
  await flow.getByLabel(t('shared.credit.cashAmount'), { exact: true }).fill('1,200')
  await flow.getByRole('button', { name: t('shared.credit.cashAdd') }).click()
  await expect(flow.getByRole('checkbox', { name: /Taxi de prueba/ })).toBeChecked() // spanish-data
  await next.click()
  await flow.getByRole('button', { name: t('shared.credit.skip') }).click()

  await flow.getByLabel(t('shared.credit.name')).fill(GROUP)
  await flow.getByRole('radio', { name: new RegExp(t('shared.credit.splitEqual')) }).check()
  await flow.getByRole('button', { name: t('shared.credit.create') }).click()
  await expect(flow).toHaveCount(0)

  const home = (await (await page.request.get('/api/shared')).json()) as SharedHome
  const made = home.groups.find((g) => g.name === GROUP)!
  const group = (await (await page.request.get(`/api/shared/groups/${made.id}`)).json()) as Group
  // RD$ 1,200 in two: her share is RD$ 600 and she paid RD$ 500, so she still owes RD$ 100.
  const amigaMember = group.members.find((m) => !m.is_me)!
  expect(amigaMember.balance).toEqual([{ currency: 'DOP', cents: 10000 }])
})
