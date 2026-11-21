import { expect, test, type Page } from '@playwright/test'
import { t } from './text'

// The cash account (schema 23) on the made-up data of tests/e2e_server.py, whose "today" is
// 2026-02-20 (the browser clock is set to the same day, so the forms default to it). It runs
// on the desktop project and at phone width (playwright.config.ts). The «+» writes a weekly
// expense dated a week ago with "Repeat": that makes today's occurrence pending in "To
// review", where it is confirmed; then the dollars are reconciled. The last test undoes the
// three changes through the change log, so the other specs see the data as it was.

const TODAY = '2026-02-20'
const WEEK_AGO = '2026-02-13'
const BOX = 'manual:cash-box'
const CASH_ACCOUNT = `/accounts?account=${encodeURIComponent(BOX)}`
const WRITE = { 'X-Michelito': '1' }
const CONCEPT = 'Cleaning'
let firstLogId = 0

test.describe.configure({ mode: 'serial' })

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(new Date(`${TODAY}T12:00:00`))
})

function card(page: Page) {
  return page.getByRole('region', { name: t('cashBox.title') })
}

test('the «+» records a cash expense that repeats every week', async ({ page }) => {
  const log = await (await page.request.get('/api/log')).json()
  firstLogId = log.items.length ? log.items[0].id : 0

  await page.goto('/')
  await page.getByRole('button', { name: t('cashBox.quick.label') }).click()
  const dialog = page.getByRole('dialog', { name: t('cashBox.quick.title') })
  await expect(dialog.getByRole('radio', { name: t('cashBox.kind.expense') })).toHaveAttribute(
    'aria-checked',
    'true',
  )
  await expect(dialog.getByLabel(t('cashBox.form.day'))).toHaveValue(TODAY)
  await dialog.getByLabel(t('cashBox.form.amount')).fill('3,000')
  await dialog.getByLabel(t('cashBox.form.concept')).fill(CONCEPT)
  await dialog.getByLabel(t('cashBox.form.day')).fill(WEEK_AGO)
  await dialog.getByLabel(t('cashBox.form.repeat')).check()
  await dialog
    .getByRole('combobox', { name: t('cashBox.form.frequency') })
    .selectOption('weekly')
  await dialog.getByRole('button', { name: t('cashBox.form.save') }).click()
  await expect(dialog).toHaveCount(0)

  // The next one is a week after today's: within the week, so the Summary says so.
  // On the Summary's «Upcoming» card, with the recurring charges.
  const upcoming = page.locator('[data-card="upcoming"]')
  await expect(upcoming).toContainText(CONCEPT)
  await expect(upcoming).toContainText('RD$ 3,000')

  await page.goto(CASH_ACCOUNT)
  const schedule = card(page).getByTestId('cash-schedule')
  await expect(schedule).toHaveCount(1)
  await expect(schedule).toContainText(CONCEPT)
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(page.viewportSize()!.width)
})

test('today’s occurrence is confirmed from To review', async ({ page }) => {
  await page.goto('/review')
  const list = page.getByRole('list', { name: t('cashBox.review.listLabel') })
  const row = list.getByTestId('cash-occurrence')
  await expect(row).toHaveCount(1)
  await expect(row).toContainText(t('cashBox.review.payment', { concept: CONCEPT }))
  const paid = row.getByRole('button', { name: t('cashBox.review.paid') })
  expect((await paid.boundingBox())!.height).toBeGreaterThanOrEqual(32)
  await paid.click()
  await expect(list).toHaveCount(0)

  await page.goto(`/transactions?month=2026-02&accounts=${encodeURIComponent(BOX)}`)
  const rows = page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .getByRole('button', { name: new RegExp(`^${CONCEPT.toUpperCase()}`) })
  await expect(rows).toHaveCount(2)
  await expect(page.getByTestId('cash-state-badge')).toHaveCount(0)
})

test('reconciling the dollars writes the unrecorded expense', async ({ page }) => {
  await page.goto(CASH_ACCOUNT)
  // The last one: with a negative balance its warning offers it too.
  await card(page).getByRole('button', { name: t('cashBox.action.reconcile') }).last().click()
  const form = card(page).getByRole('region', { name: t('cashBox.reconcile.title') })
  await form.getByLabel(t('cashBox.reconcile.have', { currency: 'US$' })).fill('150')
  await form.getByRole('button', { name: t('cashBox.reconcile.save') }).click()
  await expect(form).toHaveCount(0)
  await expect(card(page).getByTestId('cash-box-balance')).toContainText('US$ 150.00')
  const lines = card(page).getByRole('list', { name: t('cashBox.linesLabel') })
  await expect(lines.getByRole('listitem').first()).toContainText('−US$ 50.00')
})

test('the three changes are undone', async ({ page }) => {
  const log = await (await page.request.get('/api/log')).json()
  const mine = log.items.filter(
    (item: { id: number; kind: string }) => item.id > firstLogId && item.kind.startsWith('cash_'),
  )
  expect(mine.map((item: { kind: string }) => item.kind)).toEqual([
    'cash_reconcile',
    'cash_occurrence',
    'cash_entry',
  ])
  for (const item of mine) {
    const undone = await page.request.post(`/api/log/${item.id}/undo`, { headers: WRITE })
    expect(undone.status()).toBe(200)
  }
  const box = await (await page.request.get('/api/cash-box')).json()
  expect(box.schedules).toEqual([])
  expect(box.occurrences).toEqual([])
  expect(box.balances).toEqual([{ currency: 'USD', amount_cents: 20_000 }])
})

test('on a phone the «+» covers neither the bottom bar nor the last card’s links', async ({
  page,
}) => {
  test.skip(page.viewportSize()!.width >= 768, 'the floating button is a phone thing')
  await page.goto('/')
  const button = page.getByRole('button', { name: t('cashBox.quick.label') })
  await expect(page.locator('[data-card]').last()).toBeVisible()
  // Every card loaded (their skeletons gone), then to the very end of the page.
  await expect(page.locator('[data-card] [aria-busy="true"], .animate-pulse')).toHaveCount(0)
  await expect
    .poll(() =>
      page.evaluate(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })
        const root = document.documentElement
        return Math.round(root.scrollHeight - window.scrollY - root.clientHeight)
      }),
    )
    .toBe(0)
  const fab = (await button.boundingBox())!
  const bar = (await page.locator('[data-bottom-bar]').boundingBox())!
  expect(fab.y + fab.height).toBeLessThanOrEqual(bar.y)
  const overlaps = await page.evaluate(
    ({ x, y, width, height }) =>
      [...document.querySelectorAll('[data-card] a, [data-card] button')].filter((element) => {
        const r = element.getBoundingClientRect()
        return r.width > 0 && r.x < x + width && r.x + r.width > x && r.y < y + height && r.y + r.height > y
      }).map((e) => `${e.tagName}:${e.textContent?.slice(0, 30)}:${JSON.stringify(e.getBoundingClientRect())}`),
    fab,
  )
  expect(overlaps).toEqual([])
})
