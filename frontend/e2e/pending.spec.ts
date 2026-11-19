import { expect, test, type Page } from '@playwright/test'
import { escapeRegExp, literal, t } from './text'

// Made-up data from tests/e2e_server.py (`_link_pending`): a gift "I paid for someone else"
// for Luis (RD$ 4,000, Dec 20), an exchange where you gave RD$ first and are owed US$ 100
// (Dec 3) and another where you were paid and owe US$ 200 (Dec 10, with a note).
// The board.spec.ts tests may leave other pending items: these rows are looked up here.
const VISA = 'demo:credit_card'

/** The "N days ago" text, with any N. */
const DAYS_AGO = new RegExp(
  escapeRegExp(t('pending.age.daysAgo', { count: 2 })).replace('2', '\\d+'),
)

function lists(page: Page) {
  return {
    owed: page.getByRole('region', { name: t('pending.figure.owed') }),
    owe: page.getByRole('region', { name: t('pending.figure.owe') }),
  }
}

function mainNav(page: Page) {
  return page.getByRole('navigation', { name: t('shell.nav.label') })
}

function heading(page: Page) {
  return page.getByRole('heading', { level: 1, name: t('pending.title') })
}

test('the menu opens Pending with one row in each list', async ({ page }) => {
  await page.goto('/')
  await mainNav(page).getByRole('link', { name: t('shell.nav.pending') }).click()
  await expect(page).toHaveURL(/\/pending$/)
  await expect(heading(page)).toBeVisible()

  const { owed, owe } = lists(page)
  const gift = owed.getByRole('link', { name: /^Luis/ })
  // A group is named by its "With whom" (or its name); the date is its expense's.
  await expect(gift).toContainText('20 dic 2025') // spanish-ui: date built with Intl
  await expect(gift).toContainText('RD$ 4,000')
  await expect(gift).toContainText(DAYS_AGO)
  await expect(owed.getByRole('link', { name: /CAMBISTA/ })).toContainText('US$ 100.00')
  const cousin = owe.getByRole('link', { name: /PRIMO/ })
  await expect(cousin).toContainText('Cambio con Pedro') // spanish-data
  // At the exchange's agreed rate (63.10), not the latest one.
  await expect(cousin).toContainText('US$ 200.00')
  await expect(cousin).toContainText(
    `${t('pending.approx', { amount: 'RD$ 12,620' })} ${t('pending.agreedRate', { rate: '63.10' })}`,
  )
  // No shared expense in US$: no rate note.
  await expect(page.getByText(literal(t('summary.rate.otherMonth', { month: 'febrero' })))).toHaveCount(0) // spanish-ui: month name
  await expect(page.getByTestId('pending-owe')).toHaveText('RD$ 12,620')
})

test('a row opens its screen and "Back" returns to Pending', async ({ page }) => {
  await page.goto('/pending')
  await lists(page).owe.getByRole('link', { name: /PRIMO/ }).click()
  await expect(page).toHaveURL(/\/transactions\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/PRIMO/)
  await expect(page.getByTestId('exchange-line')).toContainText(
    t('links.exchange.pending', { amount: 'US$ 200.00' }),
  )

  await page.getByRole('link', { name: t('links.page.back') }).click()
  await expect(page).toHaveURL(/\/pending$/)
  await expect(heading(page)).toBeVisible()
})

test('the Summary widget has the figures of every month and leads to Pending', async ({
  page,
}) => {
  await page.goto('/?month=2026-02') // the made-up pending items are from December
  const widget = page.getByRole('region', { name: t('summary.pendingCard.title') })
  await expect(widget).toContainText(t('summary.pendingCard.note').split(';')[0])
  await expect(widget.getByTestId('pending-card-owe')).toHaveText('RD$ 12,620')
  const owed = await widget.getByTestId('pending-card-owed').textContent()
  const net = await widget.getByTestId('pending-card-net').textContent()

  await widget.getByRole('link', { name: t('summary.pendingCard.link') }).click()
  await expect(page).toHaveURL(/\/pending$/)
  await expect(page.getByTestId('pending-owed')).toHaveText(owed ?? '')
  await expect(page.getByTestId('pending-net')).toHaveText(net ?? '')
  await expect(lists(page).owed.getByRole('link', { name: /^Luis/ })).toBeVisible()
})

test('the Summary widget keeps the chosen accounts', async ({ page }) => {
  await page.goto(`/?month=2026-02&accounts=${encodeURIComponent(VISA)}`)
  const widget = page.getByRole('region', { name: t('summary.pendingCard.title') })
  await expect(widget.getByTestId('pending-card-owe')).toHaveText('RD$ 0')
  await widget.getByRole('link', { name: t('summary.pendingCard.link') }).click()
  await expect(page).toHaveURL(/\/pending\?accounts=/)
  await expect(lists(page).owe).toContainText(t('pending.oweEmpty'))
})

test('with only the VISA its expenses stay and no exchange', async ({ page }) => {
  await page.goto(`/pending?accounts=${encodeURIComponent(VISA)}`)
  const { owed, owe } = lists(page)
  await expect(owed.getByRole('link', { name: /^Luis/ })).toBeVisible()
  await expect(owed.getByRole('link', { name: /CAMBISTA/ })).toHaveCount(0)
  await expect(owe).toContainText(t('pending.oweEmpty'))
  await expect(page.getByTestId('pending-owe')).toHaveText('RD$ 0')
})

test('at 390 px it does not scroll sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/pending')
  await expect(lists(page).owe.getByRole('link', { name: /PRIMO/ })).toBeVisible()
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})
