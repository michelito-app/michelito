import { expect, test, type Locator, type Page } from '@playwright/test'
import { t } from './text'

// Made-up data from tests/e2e_server.py: the cash box starts with an initial balance of US$ 200
// (December, at 63.10 ≈ RD$ 12,620). In January 2026, on the checking account, a «RETIRO CAJERO
// SANTO DOMINGO» of RD$ 5,000 and a «DEPOSITO CLIENTE FICTICIO» of RD$ 12,000. The tests run in
// order and the last one undoes what they did (the rest of the tests does not change). An
// earlier test (board.spec.ts) moves the deposit to the between-my-accounts category, which
// cannot come from the cash box: here it goes to INCOME and at the end back to what it had.

const JANUARY = '2026-01'
const BOX = 'manual:cash-box'
// spanish-data: begin — category names seeded by the backend, and a note typed by the test
const INCOME = 'Otros ingresos'
const CASH_BOX_CATEGORY = 'Pasado a efectivo'
const CASH = 'Efectivo'
const SUPERMARKET = 'Supermercado'
const NOTE = 'Colmado de prueba'
const CONCEPT = 'Colmado'
// spanish-data: end
let depositCategory = INCOME
// The cash account in Accounts, and the expense's row (its concept is its merchant).
const CASH_ACCOUNT = `/accounts?account=${encodeURIComponent(BOX)}`
const ENTRY = new RegExp(`^${CONCEPT.toUpperCase()}`)

function categorySelect(detail: Locator) {
  // By its exact name: the label's would include the chosen option.
  return detail.getByRole('combobox', { name: t('transactions.filters.category'), exact: true })
}

async function setCategory(detail: Locator, name: string) {
  await categorySelect(detail).selectOption(name)
  await detail.getByRole('button', { name: t('transactions.save') }).click()
  await expect(categorySelect(detail)).toHaveValue(name)
  await expect(detail.getByRole('button', { name: t('transactions.save') })).toBeDisabled()
}

async function openTransaction(page: Page, name: RegExp, query = '') {
  await page.goto(`/transactions?month=${JANUARY}${query}`)
  await page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .getByRole('button', { name })
    .click()
  return page.getByRole('complementary')
}

function card(page: Page) {
  return page.getByRole('region', { name: t('cashBox.title') })
}

/** The «Cash box» section of a transaction's detail. */
function section(detail: Locator) {
  return detail.getByRole('region', { name: t('links.cashBox.title') })
}

/** On a phone the detail is full screen and its «Cash box» opens in a sheet: that sheet. */
async function phoneCashBox(page: Page, detail: Locator): Promise<Locator> {
  const mobile = page.locator('[data-mobile-detail]')
  // Decided by the viewport (the app's phone query is max-width 767.98px), not by counting: right
  // after a resize the desktop detail can still be on screen for a moment.
  if (page.viewportSize()!.width >= 768) return detail
  await mobile.waitFor()
  const open = mobile.getByRole('button', {
    name: t('transactions.links.openLabel', { what: t('transactions.actions.cashBox') }),
  })
  if ((await open.count()) > 0) await open.click()
  else await mobile.getByRole('button', { name: t('transactions.actions.cashBox'), exact: true }).click()
  return page.getByRole('dialog', { name: t('transactions.actions.cashBox') })
}

const kpiRegion = (page: Page) =>
  page.getByRole('region', { name: t('summary.kpi.sectionLabel') })

test.describe.configure({ mode: 'serial' })

test('a withdrawal is marked as stored: it stops being an expense and adds to the box', async ({
  page,
}) => {
  await page.goto(`/reports?month=${JANUARY}`)
  const kpis = kpiRegion(page)
  await expect(kpis).toBeVisible()
  await expect(kpis.getByTestId('cash-box-note')).toHaveCount(0)

  const detail = await openTransaction(page, /^RETIRO CAJERO.*RD\$ 5,000$/)
  await expect(section(detail)).toContainText(t('cashBox.tx.canStore'))
  await section(detail).getByRole('button', { name: t('links.cashBox.store') }).click()
  await expect(section(detail).getByTestId('cash-box-text')).toContainText(t('cashBox.tx.stored'))
  await expect(categorySelect(detail)).toBeDisabled()
  await expect(categorySelect(detail)).toHaveValue(CASH_BOX_CATEGORY)

  await page.goto(`/reports?month=${JANUARY}`)
  const note = kpis.getByTestId('cash-box-note')
  await expect(note).toHaveText(t('cashBox.note', { amount: 'RD$ 5,000' }))
  await note.getByRole('link').click()
  await expect(page).toHaveURL(/\/accounts#cash-box$/)
  await expect(card(page).getByTestId('cash-box-balance')).toHaveText('RD$ 5,000 + US$ 200.00')
  await expect(card(page).getByTestId('cash-box-approx')).toHaveText(
    t('cashBox.approx.total', { amount: 'RD$ 17,620' }),
  )
  const lines = card(page).getByRole('list', { name: t('cashBox.linesLabel') })
  await expect(lines).toContainText(t('cashBox.line.stored'))
  await expect(lines).toContainText(t('cashBox.line.initial'))
})

test('an expense is recorded with its category and counts as spending', async ({ page }) => {
  await page.goto(CASH_ACCOUNT)
  await card(page).getByRole('button', { name: t('cashBox.action.expense') }).click()
  const form = card(page).getByRole('region', { name: t('cashBox.entryTitle.expense') })
  await form.getByLabel(t('cashBox.form.amount')).fill('1,500')
  await form.getByLabel(t('cashBox.form.concept')).fill(CONCEPT)
  await expect(form.getByLabel(t('cashBox.form.day'))).toHaveAttribute('min', '2000-01-01')
  await expect(form.getByLabel(t('cashBox.form.day'))).toHaveAttribute(
    'max',
    /^\d{4}-\d{2}-\d{2}$/,
  )
  await form.getByLabel(t('cashBox.form.day')).fill('2026-01-20')
  await form
    .getByRole('combobox', { name: t('cashBox.form.category'), exact: true })
    .selectOption({ label: SUPERMARKET })
  await form.getByLabel(t('cashBox.form.note')).fill(NOTE)
  await form.getByRole('button', { name: t('cashBox.form.save') }).click()
  await expect(form).toHaveCount(0)
  await expect(card(page).getByTestId('cash-box-balance')).toHaveText('RD$ 3,500 + US$ 200.00')
  const lines = card(page).getByRole('list', { name: t('cashBox.linesLabel') })
  await expect(lines.getByRole('listitem').first()).toContainText(
    `${CONCEPT} · ${SUPERMARKET} · ${NOTE}`,
  )

  // The account filter: the box is one more account and the expense, a supermarket expense.
  await page.goto(`/transactions?month=${JANUARY}&accounts=${encodeURIComponent(BOX)}`)
  const list = page.getByRole('region', { name: t('common.transactionListLabel') })
  await expect(list.getByRole('button', { name: ENTRY })).toHaveCount(1)
  await expect(list.getByRole('button', { name: /RETIRO CAJERO/ })).toHaveCount(0)
  await list.getByRole('button', { name: ENTRY }).click()
  const detail = page.getByRole('complementary')
  await expect(categorySelect(detail)).toHaveValue(SUPERMARKET)
  await expect(section(detail)).toContainText(t('links.cashBox.manualExpense'))
})

test('a deposit is linked to the box: it is not income and warns about the negative balance', async ({
  page,
}) => {
  const detail = await openTransaction(page, /^DEPOSITO CLIENTE.*RD\$ 12,000$/)
  depositCategory = await categorySelect(detail).inputValue()
  if (depositCategory !== INCOME) await setCategory(detail, INCOME)
  await section(detail)
    .getByRole('button', { name: t('links.cashBox.deposit'), exact: true })
    .click()
  await expect(section(detail).getByTestId('cash-box-text')).toHaveText(t('cashBox.tx.deposit'))
  // RD$ 5,000 − 1,500 − 12,000: allowed, with a warning.
  await expect(section(detail).getByTestId('cash-box-negative')).toHaveText(
    t('cashBox.isNegative', { amount: '−RD$ 8,500' }),
  )

  await page.goto(CASH_ACCOUNT)
  await expect(card(page).getByTestId('cash-box-negative')).toHaveText(
    t('cashBox.isNegative', { amount: '−RD$ 8,500' }),
  )
  // Before saving, one more expense warns how it would end up.
  await card(page).getByRole('button', { name: t('cashBox.action.expense') }).click()
  const form = card(page).getByRole('region', { name: t('cashBox.entryTitle.expense') })
  await form.getByLabel(t('cashBox.form.amount')).fill('500')
  await expect(form.getByTestId('cash-box-would-be-negative')).toHaveText(
    t('cashBox.wouldBeNegative', { amount: '−RD$ 9,000' }),
  )
  await form.getByRole('button', { name: t('cashBox.form.cancel') }).click()
})

test('at 390 px the box and the two Summary lines fit and read well', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/accounts#cash-box')
  await expect(card(page).getByTestId('cash-box-balance')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  for (const button of await card(page).getByRole('button').all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }

  // With contributions and stored withdrawals in the same month both lines show, one below
  // the other.
  await page.route('**/api/summary?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, invested_cents: 35_000_000 } })
  })
  await page.goto(`/reports?month=${JANUARY}`)
  const kpis = kpiRegion(page)
  const invested = kpis.getByTestId('invested-note')
  const stored = kpis.getByTestId('cash-box-note')
  await expect(invested).toHaveText(t('investments.investedNote', { amount: 'RD$ 350,000' }))
  await expect(stored).toHaveText(t('cashBox.note', { amount: 'RD$ 5,000' }))
  // Both boxes in one go: measured apart, a card still loading above them could move the page
  // between the two readings.
  const [top, bottom] = await page.evaluate(() =>
    ['invested-note', 'cash-box-note'].map((id) => {
      const rect = document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect()
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    }),
  )
  expect(top && bottom).toBeTruthy()
  expect(bottom!.y).toBeGreaterThanOrEqual(top!.y + top!.height)
  for (const line of [top!, bottom!]) {
    expect(line.x).toBeGreaterThanOrEqual(0)
    expect(line.x + line.width).toBeLessThanOrEqual(390)
  }
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})

test('at 390 px the «Cash box» section of the detail fits and its targets are 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const name of [/^RETIRO CAJERO.*RD\$ 5,000$/, /^DEPOSITO CLIENTE.*RD\$ 12,000$/]) {
    const detail = await phoneCashBox(page, await openTransaction(page, name))
    const box = section(detail)
    await box.scrollIntoViewIfNeeded()
    await expect(box.getByTestId('cash-box-text')).toBeVisible()
    const bounds = (await box.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
    for (const button of await box.getByRole('button').all()) {
      const size = (await button.boundingBox())!
      expect(size.height).toBeGreaterThanOrEqual(44)
      expect(size.x + size.width).toBeLessThanOrEqual(390)
    }
    for (const link of await box.getByRole('link').all()) {
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  }
})

test('everything is undone: the deposit, the stored withdrawal and the expense', async ({
  page,
}) => {
  let detail = await openTransaction(page, /^DEPOSITO CLIENTE.*RD\$ 12,000$/)
  await detail.getByRole('button', { name: t('links.cashBox.undeposit') }).click()
  await expect(section(detail).getByTestId('cash-box-text')).toHaveText(t('cashBox.tx.canDeposit'))
  await expect(categorySelect(detail)).toHaveValue(INCOME)
  if (depositCategory !== INCOME) await setCategory(detail, depositCategory)

  detail = await openTransaction(page, /^RETIRO CAJERO.*RD\$ 5,000$/)
  await detail.getByRole('button', { name: t('links.cashBox.unstore') }).click()
  await expect(categorySelect(detail)).toHaveValue(CASH)

  // The expense is deleted from its detail: the detail closes and the URL drops ?tx=.
  detail = await openTransaction(page, ENTRY, `&accounts=${encodeURIComponent(BOX)}`)
  await expect(page).toHaveURL(/[?&]tx=cash-/)
  await section(detail).getByRole('button', { name: t('links.cashBox.delete'), exact: true }).click()
  await expect(
    page.getByRole('alertdialog', { name: t('links.cashBox.deleteLabel') }),
  ).toContainText(t('cashBox.delete.warning'))
  await page.getByRole('button', { name: t('links.cashBox.deleteConfirm') }).click()
  // Closed: the panel goes back to an empty «Detail» (on the phone, it does not even show).
  await expect(
    page.getByRole('complementary', { name: t('transactions.detail.label') }),
  ).toContainText(t('transactions.detail.empty'))
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page).not.toHaveURL(/[?&]tx=/)
  const list = page.getByRole('region', { name: t('common.transactionListLabel') })
  await expect(list.getByRole('button', { name: ENTRY })).toHaveCount(0)

  await page.goto(CASH_ACCOUNT)
  await expect(card(page).getByTestId('cash-box-balance')).toHaveText('US$ 200.00')
  await expect(card(page).getByTestId('cash-box-negative')).toHaveCount(0)

  await page.goto(`/reports?month=${JANUARY}`)
  await expect(kpiRegion(page)).toBeVisible()
  await expect(page.getByTestId('cash-box-note')).toHaveCount(0)
})
