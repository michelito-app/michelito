import { expect, test, type Locator, type Page } from '@playwright/test'
import { escapeRegExp, t } from './text'

// Merchant receipts on their own server (tests/e2e_server.py --receipts, see
// tests/e2e_receipts.py): the base data plus three made-up Amazon charges in February and two
// synthetic shipment emails. One email names a single charge (linked on its own); the other
// names an amount two charges share (To review). Runs on a desktop, on a phone and on WebKit at
// an iPhone's size; each test starts from the same database (reset route).
const MONTH = '2026-02'
const WRITE = { 'X-Michelito': '1' }
const ORDER = '111-1111111-1111111'
const LINKED_TITLE = `Amazon: ${t('receipts.items', { count: 3 })}, Kitchen`
const PROPOSED_TITLE = `Amazon: ${t('receipts.items', { count: 1 })}, Tools`
const LINKED_STATEMENT = 'AMAZON MKTPL*AB1CD2EF3'
const TWIN = /AMAZON RETAIL/

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ request }) => {
  expect((await request.post('/e2e/live/reset', { headers: WRITE })).ok()).toBe(true)
})

/** The accessible name of an answer button, whatever merchant name the row carries. */
function answer(key: 'receipts.review.yesLabel' | 'receipts.review.noLabel'): RegExp {
  const [before, after] = t(key, { merchant: '\u0000' }).split('\u0000')
  return new RegExp(`^${escapeRegExp(before)}.+${escapeRegExp(after)}$`)
}

function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 1280) < 768
}

function rows(page: Page): Locator {
  return page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .locator('[data-fingerprint]')
}

function detail(page: Page): Locator {
  return isPhone(page) ? page.locator('[data-mobile-detail]') : page.getByRole('complementary')
}

test('a linked charge is titled by its receipt, with the statement name under it', async ({
  page,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  const row = rows(page).filter({ hasText: LINKED_TITLE })
  await expect(row).toHaveCount(1)
  await expect(row.getByTestId('bank-name')).toContainText('AMAZON')
  // The two charges still waiting keep the statement's own name.
  await expect(rows(page).filter({ hasText: TWIN })).toHaveCount(0)
  await expect(rows(page).filter({ hasText: 'AMAZON' })).toHaveCount(3)

  await row.click()
  const panel = detail(page)
  await expect(panel.getByRole('heading', { level: 2 })).toHaveText(LINKED_TITLE)
  await expect(panel.getByText(LINKED_STATEMENT)).toBeVisible()
  const box = panel.getByTestId('receipt-box')
  await expect(box).toContainText(t('receipts.kind.shipment'))
  await expect(box).toContainText(t('receipts.box.order', { order: ORDER }))
  await expect(box).toContainText(t('receipts.box.automatic'))
  await expect(
    box.getByRole('link', { name: t('receipts.box.openEmailLabel', { merchant: 'Amazon' }) }),
  ).toHaveAttribute('href', /^https:\/\/mail\.google\.com\/mail\/u\/0\/#all\/e2e-receipt-1$/)
  await expect(
    box.getByRole('link', {
      name: t('receipts.box.openOrderLabel', { order: ORDER, merchant: 'Amazon' }),
    }),
  ).toHaveAttribute('href', new RegExp(`^https://www\\.amazon\\.com/.*orderID=${ORDER}$`))
})

test('the receipt box fits the screen without sideways scrolling', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await rows(page).filter({ hasText: LINKED_TITLE }).click()
  const box = detail(page).getByTestId('receipt-box')
  await expect(box).toBeVisible()

  const size = await box.boundingBox()
  const viewport = page.viewportSize()
  expect(size).not.toBeNull()
  expect(size!.x).toBeGreaterThanOrEqual(0)
  expect(size!.x + size!.width).toBeLessThanOrEqual(viewport!.width)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})

test('taking the receipt off gives the charge back its statement name', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await rows(page).filter({ hasText: LINKED_TITLE }).click()
  const panel = detail(page)
  await panel.getByRole('button', { name: t('receipts.box.removeLabel', { order: ORDER }) }).click()

  await expect(panel.getByTestId('receipt-box')).toHaveCount(0)
  await expect(panel.getByRole('heading', { level: 2 })).not.toHaveText(LINKED_TITLE)

  await page.goto(`/transactions?month=${MONTH}`)
  await expect(rows(page).filter({ hasText: LINKED_TITLE })).toHaveCount(0)
  await expect(rows(page).filter({ hasText: 'AMAZON' })).toHaveCount(3)
  // It was refused, not left to be proposed again.
  await page.goto(`/review?month=${MONTH}`)
  const review = page.locator('section[aria-labelledby="review-title"]')
  await expect(
    review.getByRole('listitem').filter({ hasText: t('review.kind.possibleReceipt') }),
  ).toHaveCount(2)
})

test('two equal charges wait in To review and choosing one links it', async ({ page }) => {
  await page.goto(`/review?month=${MONTH}`)
  const review = page.locator('section[aria-labelledby="review-title"]')
  const items = review.getByRole('listitem').filter({ hasText: t('review.kind.possibleReceipt') })
  await expect(items).toHaveCount(2)
  await expect(items.first()).toContainText('222-2222222-2222222')

  await items
    .first()
    .getByRole('button', { name: answer('receipts.review.yesLabel') })
    .click()
  await expect(items).toHaveCount(0)

  await page.goto(`/transactions?month=${MONTH}`)
  await expect(rows(page).filter({ hasText: PROPOSED_TITLE })).toHaveCount(1)
  await expect(rows(page).filter({ hasText: LINKED_TITLE })).toHaveCount(1)
})

test('answering no on one candidate links the other on its own', async ({ page }) => {
  await page.goto(`/review?month=${MONTH}`)
  const review = page.locator('section[aria-labelledby="review-title"]')
  const items = review.getByRole('listitem').filter({ hasText: t('review.kind.possibleReceipt') })
  await expect(items).toHaveCount(2)

  await items
    .first()
    .getByRole('button', { name: answer('receipts.review.noLabel') })
    .click()
  await expect(items).toHaveCount(0)

  await page.goto(`/transactions?month=${MONTH}`)
  await expect(rows(page).filter({ hasText: PROPOSED_TITLE })).toHaveCount(1)
})
