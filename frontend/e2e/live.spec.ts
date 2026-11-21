import { expect, test, type Locator, type Page } from '@playwright/test'
import { escapeRegExp, t } from './text'

// Live sync on its own server (tests/e2e_server.py --live, see tests/e2e_live.py): the base data
// plus three made-up provisional purchases on the synthetic Popular card in February. Runs on a
// desktop and on a phone; each test starts from the same database (reset route).
const MONTH = '2026-02'
const COLMADO = /COLMADO FICTICIO/
const BOOKSTORE = /LIBRERIA FICTICIA/
const SHOES = /ZAPATERIA FICTICIA/
const HEALTH = 'Salud' // spanish-data
const WRITE = { 'X-Michelito': '1' }
const PENDING = t('transactions.badge.provisional')

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ request }) => {
  expect((await request.post('/e2e/live/reset', { headers: WRITE })).ok()).toBe(true)
})

function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 1280) < 768
}

function list(page: Page): Locator {
  return page.getByRole('region', { name: t('common.transactionListLabel') })
}

function row(page: Page, name: RegExp): Locator {
  return list(page).locator('[data-fingerprint]').filter({ hasText: name })
}

function detail(page: Page): Locator {
  return isPhone(page) ? page.locator('[data-mobile-detail]') : page.getByRole('complementary')
}

/** Turns on the pending-statement filter: in the search row on a desktop, in the sheet on a phone. */
async function onlyProvisional(page: Page): Promise<void> {
  const search = page.getByRole('search')
  const name = t('transactions.filters.provisional')
  if (isPhone(page)) {
    await search
      .getByRole('button', { name: new RegExp(`^${escapeRegExp(t('transactions.filters.title'))}`) })
      .click()
    const sheet = page.getByRole('dialog', { name: t('transactions.filters.title') })
    await sheet.getByRole('button', { name }).click()
    await expect(sheet.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true')
    await sheet.getByRole('button', { name: t('transactions.filters.done') }).click()
    await expect(sheet).toHaveCount(0)
  } else {
    await search.getByRole('button', { name }).click()
  }
}

test('provisional rows carry the badge and the filter leaves only them', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}`)
  for (const name of [COLMADO, BOOKSTORE, SHOES]) {
    await expect(row(page, name)).toContainText(PENDING)
  }
  const statementRow = row(page, /SUPERMERCADO FICTICIO/)
  await expect(statementRow).toHaveCount(1)
  await expect(statementRow).not.toContainText(PENDING)

  await onlyProvisional(page)
  await expect(page).toHaveURL(/provisional=1/)
  await expect(list(page).locator('[data-fingerprint]')).toHaveCount(3)
})

test('a provisional can be categorized and its detail says it is pending', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await row(page, BOOKSTORE).click()
  const panel = detail(page)
  await expect(panel.getByTestId('provisional-note')).toContainText(
    t('transactions.provisional.title'),
  )
  if (isPhone(page)) {
    const change = escapeRegExp(t('transactions.detail.changeCategory', { category: '@' }))
    await panel.getByRole('button', { name: new RegExp(change.replace('@', '.*')) }).click()
    const sheet = page.getByRole('dialog')
    await sheet.getByLabel(t('transactions.filters.category')).selectOption(HEALTH)
    await sheet.getByLabel(t('transactions.detail.onlyThis')).check()
    await sheet.getByRole('button', { name: t('transactions.save') }).click()
    await expect(sheet).toHaveCount(0)
    await panel.getByRole('button', { name: t('transactions.detail.back') }).click()
  } else {
    await panel.getByLabel(t('transactions.filters.category')).selectOption(HEALTH)
    await panel.getByLabel(t('transactions.detail.onlyThis')).check()
    await panel.getByRole('button', { name: t('transactions.save') }).click()
    await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()
  }
  await expect(row(page, BOOKSTORE)).toContainText(HEALTH)
  await expect(row(page, BOOKSTORE)).toContainText(PENDING)
})

test('a statement confirms one; the one it lacks is to review and can be discarded', async ({
  page,
  request,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await expect(row(page, COLMADO)).toContainText(PENDING)
  const before = await row(page, COLMADO).getAttribute('data-fingerprint')
  const stored = await request.post('/e2e/live/statement', { headers: WRITE })
  expect(await stored.json()).toEqual({ status: 'parsed' })

  await page.reload()
  await expect(row(page, COLMADO)).toHaveCount(1) // the same row, now confirmed
  await expect(row(page, COLMADO)).toHaveAttribute('data-fingerprint', before!)
  await expect(row(page, COLMADO)).not.toContainText(PENDING)
  await expect(row(page, BOOKSTORE)).toContainText(PENDING)

  await page.goto(`/review?month=${MONTH}`)
  const review = page.locator('section[aria-labelledby="review-title"]')
  const item = review.getByRole('listitem').filter({ hasText: SHOES })
  await expect(item).toContainText(t('review.kind.unconfirmed'))
  const merchant = 'ZAPATERIA FICTICIA'
  await expect(item.getByRole('button', { name: t('review.row.keepLabel', { merchant }) })).toBeVisible()
  await item.getByRole('button', { name: t('review.row.discardLabel', { merchant }) }).click()
  await expect(review.getByRole('listitem').filter({ hasText: SHOES })).toHaveCount(0)

  await page.goto(`/transactions?month=${MONTH}`)
  await expect(row(page, BOOKSTORE)).toHaveCount(1)
  await expect(row(page, SHOES)).toHaveCount(0)
})

test('the Summary says how much of the month is still without a statement', async ({ page }) => {
  await page.goto(`/?month=${MONTH}`)
  // RD$ 845 + RD$ 1,230 + RD$ 990
  await expect(page.getByTestId('provisional-total').first()).toHaveText(
    t('summary.provisional', { amount: 'RD$ 3,065' }),
  )
})
