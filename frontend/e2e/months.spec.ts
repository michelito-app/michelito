import { expect, test, type Page } from '@playwright/test'
import { LOCALE } from '../src/i18n'
import { literal, t } from './text'

/** "2026-01" → the month name as the app writes it in phrases (Intl, lowercase). */
function monthName(month: string): string {
  return new Intl.DateTimeFormat(LOCALE, { month: 'long', timeZone: 'UTC' }).format(
    new Date(`${month}-01T00:00:00Z`),
  )
}

/** "2026-01" → the month title the app shows (capitalized name and year). */
function monthTitle(month: string): string {
  const name = monthName(month)
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${month.slice(0, 4)}`
}

// Made-up data from tests/e2e_server.py: there are December 2025, January and February 2026.
// January and February are in progress, so the default month is December 2025.
const title = (page: Page) => page.getByRole('heading', { level: 1 }).getByRole('button')
const grid = (page: Page) => page.getByRole('dialog', { name: t('months.pick') })
const nav = (page: Page) => page.getByRole('navigation', { name: t('shell.nav.label') })

test('transactions: the arrows change the month and keep the search and the filters', async ({
  page,
}) => {
  await page.goto('/transactions?month=2026-01&q=DEPOSITO&kind=income&group=category')
  await expect(page.getByRole('heading', { level: 1, name: monthTitle('2026-01') })).toBeVisible()
  // There is no month field in the filters any more (the old label, which has no key now).
  await expect(page.getByRole('search').getByLabel('Mes')).toHaveCount(0) // spanish-ui

  await page.getByRole('button', { name: t('months.previous') }).click()

  await expect(page.getByRole('heading', { level: 1, name: monthTitle('2025-12') })).toBeVisible()
  const url = new URL(page.url())
  expect(url.searchParams.get('month')).toBe('2025-12')
  expect(url.searchParams.get('q')).toBe('DEPOSITO')
  expect(url.searchParams.get('kind')).toBe('income')
  expect(url.searchParams.get('group')).toBe('category')
  await expect(page.getByRole('searchbox')).toHaveValue('DEPOSITO')
  await expect(page.getByRole('search').getByLabel(t('transactions.filters.kind'))).toHaveValue('income')
  await expect(page.getByRole('main').locator('header')).toContainText(
    t('months.headerScope', {
      last: 31,
      month: monthName('2025-12'),
      scope: t('common.allYourAccounts'),
    }),
  )

  await page.getByRole('button', { name: t('months.next') }).click()
  await expect(page).toHaveURL(/month=2026-01/)
  await expect(page.getByRole('searchbox')).toHaveValue('DEPOSITO')
})

test('transactions: «Back to …» returns to the default month and keeps the search', async ({
  page,
}) => {
  await page.goto('/transactions?month=2026-02&q=FICTICIO')
  await page.getByRole('button', { name: t('months.backTo', { month: monthTitle('2025-12') }) }).click()

  await expect(page.getByRole('heading', { level: 1, name: monthTitle('2025-12') })).toBeVisible()
  await expect(page).not.toHaveURL(/month=/)
  await expect(page).toHaveURL(/q=FICTICIO/)
  await expect(page.getByRole('button', { name: literal(t('months.backTo', { month: '' }).trim()) })).toHaveCount(0)
})

for (const route of ['/', '/transactions']) {
  test(`grid (${route}): jumps to a month of another year`, async ({ page }) => {
    await page.goto(`${route}?month=2026-02${route === '/' ? '' : '&q=FICTICIO'}`)
    await expect(title(page)).toHaveAttribute('aria-expanded', 'false')
    await title(page).click()

    await expect(title(page)).toHaveAttribute('aria-expanded', 'true')
    await expect(grid(page)).toContainText('2026')
    // Months without data cannot be picked.
    await expect(grid(page).getByRole('button', { name: literal(monthTitle('2026-03'), { start: true }) })).toBeDisabled()
    await expect(grid(page).getByRole('button', { name: literal(monthTitle('2026-02'), { start: true }) })).toHaveAttribute(
      'aria-current',
      'date',
    )
    // Only years with data exist: there is none after 2026.
    await expect(grid(page).getByRole('button', { name: t('months.nextYear') })).toHaveAttribute(
      'aria-disabled',
      'true',
    )

    await grid(page).getByRole('button', { name: t('months.previousYear') }).click()
    await expect(grid(page)).toContainText('2025')
    await grid(page).getByRole('button', { name: literal(monthTitle('2025-12'), { start: true }) }).click()

    await expect(grid(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { level: 1, name: monthTitle('2025-12') })).toBeVisible()
    await expect(title(page)).toBeFocused()
    await expect(page).toHaveURL(/month=2025-12/)
    if (route !== '/') await expect(page).toHaveURL(/q=FICTICIO/)
  })
}

test('grid: works with the keyboard', async ({ page }) => {
  await page.goto('/?month=2026-02')
  await title(page).focus()
  await page.keyboard.press('Enter')

  // On opening, focus is on the chosen month.
  const february = grid(page).getByRole('button', { name: literal(monthTitle('2026-02'), { start: true }) })
  await expect(february).toBeFocused()
  await page.keyboard.press('ArrowLeft')
  await expect(grid(page).getByRole('button', { name: literal(monthTitle('2026-01'), { start: true }) })).toBeFocused()
  // There are no months with data right of February: focus stays.
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await expect(february).toBeFocused()

  // Escape closes it and returns focus to the title.
  await page.keyboard.press('Escape')
  await expect(grid(page)).toHaveCount(0)
  await expect(title(page)).toBeFocused()

  await page.keyboard.press('Enter')
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: monthTitle('2026-01') })).toBeVisible()
  await expect(page).toHaveURL(/month=2026-01/)
})

test('grid: a click outside closes it', async ({ page }) => {
  await page.goto('/?month=2026-02')
  await title(page).click()
  await expect(grid(page)).toBeVisible()
  // An empty corner of the page, far from the panel.
  await page.getByRole('main').click({ position: { x: 4, y: 4 } })
  await expect(grid(page)).toHaveCount(0)
  await expect(page).toHaveURL(/month=2026-02/)
})

test('the menu carries the month between Summary and Transactions', async ({ page }) => {
  // On the default month the links carry no month.
  await page.goto('/')
  await expect(nav(page).getByRole('link', { name: t('shell.nav.transactions') })).toHaveAttribute(
    'href',
    '/transactions',
  )

  await page.goto('/?month=2026-01')
  await nav(page).getByRole('link', { name: t('shell.nav.transactions') }).click()
  await expect(page).toHaveURL(/\/transactions\?month=2026-01$/)
  await expect(page.getByRole('heading', { level: 1, name: monthTitle('2026-01') })).toBeVisible()

  // From Transactions only the month travels: neither the search nor the filters.
  await page.getByRole('button', { name: t('months.next') }).click()
  await page.getByRole('searchbox').fill('FICTICIO')
  await expect(page).toHaveURL(/q=FICTICIO/)
  await expect(nav(page).getByRole('link', { name: t('shell.nav.summary') })).toHaveAttribute(
    'href',
    '/?month=2026-02',
  )
  // The other screens carry no month.
  await expect(nav(page).getByRole('link', { name: t('shell.nav.pending') })).toHaveAttribute(
    'href',
    '/pending',
  )
  await nav(page).getByRole('link', { name: t('shell.nav.summary') }).click()
  await expect(page.getByRole('heading', { level: 1, name: monthTitle('2026-02') })).toBeVisible()
  await expect(page).toHaveURL(/\/\?month=2026-02$/)

  // Back on the default month, the link carries no month again.
  await page.getByRole('button', { name: t('months.backTo', { month: monthTitle('2025-12') }) }).click()
  await expect(nav(page).getByRole('link', { name: t('shell.nav.transactions') })).toHaveAttribute(
    'href',
    '/transactions',
  )
})

test('at 390 px: no sideways scroll and the grid as a bottom sheet', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const route of ['/?month=2026-02', '/transactions?month=2026-02']) {
    await page.goto(route)
    await expect(page.getByRole('heading', { level: 1, name: monthTitle('2026-02') })).toBeVisible()
    await title(page).click()
    await expect(grid(page)).toBeVisible()
    // Stuck to the bottom and edge to edge (once it has slid in).
    await expect
      .poll(async () => {
        const box = (await grid(page).boundingBox())!
        return [box.x, box.width, box.y + box.height].map(Math.round)
      }, { message: route })
      .toEqual([0, 390, 844])
    // Touch targets of at least 44 px.
    for (const height of await grid(page)
      .getByRole('button')
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height)))
      expect(height, route).toBeGreaterThanOrEqual(44)
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, route).toBeLessThanOrEqual(390)

    await grid(page).getByRole('button', { name: literal(monthTitle('2026-01'), { start: true }) }).click()
    await expect(page.getByRole('heading', { level: 1, name: monthTitle('2026-01') })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    )
  }
})

test('at 390 px: the sheet is modal; tapping the backdrop closes it and focus returns to the title', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?month=2026-02')
  await title(page).click()
  await expect(grid(page)).toHaveAttribute('aria-modal', 'true')

  // Tab cycles inside the sheet (previous year and the chosen month; next year has nowhere to
  // go but stays focusable).
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('Tab')
    expect(await grid(page).evaluate((el) => el.contains(document.activeElement))).toBe(true)
  }

  // The dimmed backdrop, above the sheet.
  await page.mouse.click(195, 100)
  await expect(grid(page)).toHaveCount(0)
  await expect(title(page)).toBeFocused()
  await expect(page).toHaveURL(/month=2026-02/)
})
