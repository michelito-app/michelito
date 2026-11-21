import { expect, test, type Page } from '@playwright/test'
import { message } from '../src/i18n'
import { logMark, undoSince } from './ledger'
import { escapeRegExp, literal, t } from './text'

// Made-up data from tests/e2e_server.py. January 2026 is a month with purchases on three cards.
// The server keeps a single database: the tests that correct data use different transactions
// (CAFE FICTICIO, GASOLINERA FICTICIA) and the others do not depend on the order of categories.
const MONTH = '2026-01'
// Made-up card with a statement paid in part and interest on the next statement.
const INTEREST_CARD_PAGE = '/accounts?account=ficticio%3Acredit_card'

// Month and day names are written by Intl (es-DO), not by the catalog.
const JANUARY = 'enero' // spanish-ui
const FEBRUARY_NAME = 'febrero' // spanish-ui
const JANUARY_TITLE = 'Enero 2026' // spanish-ui
const DECEMBER_TITLE = 'Diciembre 2025' // spanish-ui
const FEBRUARY_TITLE = 'Febrero 2026' // spanish-ui
const JANUARY_PHRASE = 'enero 2026' // spanish-ui
const DECEMBER_PHRASE = 'diciembre 2025' // spanish-ui
const JAN_15 = '15 ene' // spanish-ui
const FEB_22 = '22 feb' // spanish-ui
const TUESDAY_JAN_20 = 'Martes 20 de enero' // spanish-ui
const MONDAY_JAN_5 = 'Lunes 5 de enero' // spanish-ui

// Category names seeded by the backend (src/michelito/analysis/categories.py) and the made-up
// data's own names.
const THIRD_PARTY = t('categories.builtin.thirdParty')
const LOANS = 'Préstamos' // spanish-data
const OWN_TRANSFER = 'Entre mis cuentas' // spanish-data
const CURRENCY_EXCHANGE = 'Cambio de divisas' // spanish-data
const OTHERS = 'Otros' // spanish-data
const HEALTH = 'Salud' // spanish-data
const RESTAURANTS = 'Restaurantes' // spanish-data
const HOME = 'Hogar' // spanish-data
// Reason the backend gives for a suggested one-off (src/michelito/i18n/es_analysis.py).
const NEW_MERCHANT = 'comercio nuevo' // spanish-data
const CAR_CARE = 'Mantenimiento del vehículo' // spanish-data
const CINEMA = 'Cine y teatro' // spanish-data
const DINNER_NOTE = 'Cena con Ana y Luis' // spanish-data
// Alert text the backend writes for a price increase (src/michelito/i18n/es_web.py).
const PRICE_UP = 'Subió de US$ 9.99 a US$ 11.99' // spanish-data
// The word every atypical-month text has (legend and note).
const ATYPICAL = 'atípico' // spanish-ui

const LIST = t('transactions.list.label')
const KPIS = t('summary.kpi.sectionLabel')

/** A catalog template as a RegExp source: literal text, and each `{name}` replaced by the
 * RegExp source in `values`. */
function templateSource(text: string, values: Record<string, string>): string {
  return escapeRegExp(text).replace(/\\\{(\w+)\\\}/g, (whole, name: string) => values[name] ?? whole)
}

/** The text of a catalog template before its `{name}` placeholder. */
function before(text: string, name: string): string {
  return text.slice(0, text.indexOf(`{${name}}`))
}

/** A KPI label followed by its value (`value` is a RegExp source). */
function kpi(label: string, value: string): RegExp {
  return new RegExp(`${escapeRegExp(label)}\\s*${value}`)
}

test('summary: the first category opens the filtered transactions', async ({ page }) => {
  await page.goto(`/?month=${MONTH}`)
  await expect(page.getByRole('heading', { level: 1, name: JANUARY_TITLE })).toBeVisible()

  await page.locator('[data-card="categories"]').getByRole('listitem').first().getByRole('link').click()

  await expect(page).toHaveURL(/category=/)
  const category = new URL(page.url()).searchParams.get('category')!
  await expect(page.getByRole('heading', { level: 1, name: t('transactions.title') })).toBeVisible()
  const rows = page.getByRole('region', { name: LIST }).getByRole('button')
  await expect(rows.first()).toBeVisible()
  for (const row of await rows.all()) await expect(row).toContainText(category)
})

test("summary: the month's flow shows income, spending and what was left", async ({ page }) => {
  // January 2026: payroll and a deposit of the made-up checking account plus the credits of the
  // BHD savings account; spending adds the ATM withdrawal and the loan payment. The card payment
  // does not count. Before it was Spending 16,573, Left 85,428 and 84 %: the demo gained a loan
  // payment (AUT PAGO, RD$ 2,000, spending) and a transfer to third parties (MB a, RD$ 3,000,
  // which only subtracts from what was left).
  await page.goto(`/reports?month=${MONTH}`)
  const scope = t('months.headerScope', {
    last: 31,
    month: JANUARY,
    scope: t('common.allYourAccounts'),
  })
  await expect(page.getByText(literal(scope, { start: true }))).toBeVisible()
  const kpis = page.getByRole('region', { name: KPIS })
  await expect(kpis).toContainText(kpi(t('summary.kpi.income'), 'RD\\$\\s*102,001'))
  await expect(kpis).toContainText(kpi(t('summary.kpi.spending'), 'RD\\$\\s*18,573'))
  await expect(kpis).toContainText(kpi(t('summary.kpi.net'), 'RD\\$\\s*80,428'))
  await expect(kpis).toContainText(kpi(t('summary.kpi.savings'), '79 %'))
  // What was there before is still in view.
  await expect(kpis).toContainText(t('summary.kpi.oneOffs'))
  await expect(kpis).toContainText(t('summary.kpi.dollars'))
})

test('summary: the spending link opens the month\'s spending grouped by category', async ({
  page,
}) => {
  await page.goto(`/reports?month=${MONTH}`)
  const kpis = page.getByRole('region', { name: KPIS })
  await kpis.getByRole('link', { name: t('summary.kpi.spendingLink'), exact: true }).click()

  await expect(page).toHaveURL(/month=2026-01/)
  await expect(page).toHaveURL(/kind=expense/)
  await expect(page).toHaveURL(/group=category/)
  // The list total is the same as the Summary's Spending card.
  await expect(page.getByRole('main').locator('header')).toContainText('RD$ 18,573')
  const list = page.getByRole('region', { name: LIST })
  await expect(list.getByRole('button').first()).toBeVisible()
  for (const row of await list.getByRole('button').all()) {
    await expect(row).not.toContainText(t('transactions.badge.income'))
  }
})

test('summary: transfers to third parties subtract from what was left and open their list', async ({
  page,
}) => {
  await page.goto(`/reports?month=${MONTH}`)
  const kpis = page.getByRole('region', { name: KPIS })
  await expect(kpis).toContainText(kpi(t('summary.kpi.thirdParty'), 'RD\\$\\s*3,000'))
  await expect(kpis).toContainText(t('summary.net.lessThirdParty'))
  // It is not a spending category.
  await expect(
    page
      .getByRole('region', { name: t('summary.categories.title') })
      .getByRole('link', { name: literal(THIRD_PARTY) }),
  ).toHaveCount(0)

  await kpis.getByRole('link', { name: t('summary.kpi.thirdPartyLinkLabel'), exact: true }).click()
  await expect(page).toHaveURL(literal(new URLSearchParams({ category: THIRD_PARTY }).toString()))
  await expect(page).toHaveURL(/month=2026-01/)
  const list = page.getByRole('region', { name: LIST })
  await expect(list.getByRole('button', { name: /^MB A .*RD\$ 3,000$/ })).toBeVisible()
  for (const row of await list.getByRole('button').all()) {
    await expect(row).toContainText(THIRD_PARTY)
  }
})

test('transactions: the category picker lists the new categories in their group', async ({
  page,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await page.getByRole('button', { name: /AUT PAGO/ }).click()
  const select = page.getByRole('complementary').getByLabel(t('transactions.filters.category'))
  await expect(select).toHaveValue(LOANS)
  await expect(
    select.locator(`optgroup[label="${t('categories.group.expense')}"] option[value="${LOANS}"]`),
  ).toHaveCount(1)
  await expect(
    select.locator(
      `optgroup[label="${t('categories.group.transfer')}"] option[value="${THIRD_PARTY}"]`,
    ),
  ).toHaveCount(1)
})

test('summary: if a bank account ends earlier, the income says through when', async ({ page }) => {
  await page.route('**/api/summary?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, income_through: '2026-01-15', savings_rate: null } })
  })
  await page.goto(`/reports?month=${MONTH}`)
  const kpis = page.getByRole('region', { name: KPIS })
  // The cut-off note keeps its words together (non-breaking spaces).
  const through = escapeRegExp(t('summary.income.through', { day: JAN_15 })).replace(/ /g, ' ')
  await expect(kpis).toContainText(kpi(t('summary.kpi.income'), `RD\\$\\s*102,001\\s*${through}`))
  await expect(kpis).toContainText(
    kpi(
      t('summary.kpi.savings'),
      `—\\s*${escapeRegExp(t('summary.savings.incomeThrough', { day: JAN_15 }))}`,
    ),
  )
})

test('summary: an atypical month is flagged and «What happened» links its transactions', async ({
  page,
}) => {
  // The made-up data does not have enough months for the usual: December is flagged by hand
  // with what the server would send (see tests/test_anomalies.py for the rule).
  await page.route('**/api/summary?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    const trend = body.trend.map((point: { month: string }) =>
      point.month === '2025-12'
        ? { ...point, spent_flag: 'up', spent_habitual_cents: 500_000, income_flag: null }
        : point,
    )
    const what_happened = [
      {
        side: 'expense',
        merchant: 'FERRETERIA INVENTADA',
        category: HOME,
        amount_cents: 980_000,
        habitual_cents: 0,
        diff_cents: 980_000,
        count: 1,
        fingerprint: 'made-up-fingerprint',
        day: '2025-12-06',
        description: 'FERRETERIA INVENTADA SANTIAGO',
      },
    ]
    await route.fulfill({ response, json: { ...body, trend, what_happened } })
  })
  await page.goto('/reports?month=2025-12')
  const chart = page.getByRole('region', { name: t('summary.trendBars.title') })
  await expect(chart).toContainText(
    `▲▼ ${t('summary.atypical.legend', { percent: 30, floor: 'RD$ 10,000' })}`,
  )
  const deviation = t('summary.flag.deviation.vs', {
    what: t('summary.flag.deviation.spent', { amount: 'RD$ 19,883' }),
    percent: '+298%',
  })
  await expect(
    chart.getByRole('button', {
      name: new RegExp(
        `^${DECEMBER_PHRASE}.*${escapeRegExp(`${t('summary.flag.spentHigh')}: ${deviation}`)}`,
      ),
    }),
  ).toBeVisible()
  const reading = page.getByRole('region', { name: t('summary.reading.title') })
  await reading.getByRole('tab', { name: t('summary.reading.tab.whatHappened') }).click()
  const card = reading.getByRole('tabpanel')
  await expect(card).toContainText(
    t('summary.flag.sentence.withHabitual', {
      sentence: t('summary.flag.sentence.spentUp', { amount: 'RD$ 19,883' }),
      habitual: 'RD$ 5,000',
    }),
  )
  const link = card.getByRole('link', {
    name: literal(t('summary.whatHappened.openLabel', { merchant: 'FERRETERIA INVENTADA', diff: '+RD$ 9,800' })),
  })
  await expect(link).toHaveAttribute('href', '/transactions?month=2025-12&tx=made-up-fingerprint')
})

test('summary: a normal month has no «What happened»', async ({ page }) => {
  await page.goto('/reports?month=2025-12')
  await expect(page.getByRole('heading', { level: 1, name: DECEMBER_TITLE })).toBeVisible()
  await expect(page.getByRole('region', { name: t('summary.trendBars.title') })).not.toContainText(
    ATYPICAL,
  )
  await expect(page.getByRole('tab', { name: t('summary.reading.tab.whatHappened') })).toHaveCount(0)
})

test('summary: clicking a bar of the last 12 months opens that month', async ({ page }) => {
  await page.goto(`/reports?month=${MONTH}`)
  await expect(page.getByRole('heading', { level: 1, name: JANUARY_TITLE })).toBeVisible()
  const months = page
    .getByRole('region', { name: t('summary.trendBars.title') })
    .getByRole('list', { name: t('summary.trendBars.monthsLabel') })

  // Hovering shows the month's detail.
  await months.getByRole('button').first().hover()
  await expect(page.getByTestId('trend-tip')).toContainText(new RegExp(`^${DECEMBER_PHRASE}`, 'i'))

  // The first column is the chart's oldest month (December 2025 in the made-up data).
  await months.getByRole('button').first().click()

  await expect(page).toHaveURL(/month=2025-12/)
  await expect(page.getByRole('heading', { level: 1, name: DECEMBER_TITLE })).toBeVisible()
  await expect(months.getByRole('button', { name: new RegExp(`^${DECEMBER_PHRASE}`) })).toHaveAttribute(
    'aria-current',
    'true',
  )

  // With the keyboard: from January, Shift+Tab to December and Enter.
  await page.goto(`/reports?month=${MONTH}`)
  await months.getByRole('button', { name: new RegExp(`^${JANUARY_PHRASE}`) }).focus()
  await page.keyboard.press('Shift+Tab')
  await expect(months.getByRole('button', { name: new RegExp(`^${DECEMBER_PHRASE}`) })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/month=2025-12/)
  await expect(page.getByRole('heading', { level: 1, name: DECEMBER_TITLE })).toBeVisible()
})

test('summary: «Back to» returns to the current month and goes away', async ({ page }) => {
  // The Summary opens the newest month, in progress (February 2026 in the made-up data).
  const backTo = literal(t('months.backTo', { month: '' }))
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: FEBRUARY_TITLE })).toBeVisible()
  await expect(page.getByRole('button', { name: backTo })).toHaveCount(0)

  await page.getByRole('button', { name: t('months.previous') }).click()
  await expect(page.getByRole('heading', { level: 1, name: JANUARY_TITLE })).toBeVisible()

  await page.getByRole('button', { name: t('months.backTo', { month: FEBRUARY_TITLE }) }).click()
  await expect(page.getByRole('heading', { level: 1, name: FEBRUARY_TITLE })).toBeVisible()
  await expect(page).not.toHaveURL(/month=/)
  await expect(page.getByRole('button', { name: backTo })).toHaveCount(0)
})

test('summary: the KPI figures never break across two lines', async ({ page }) => {
  // Large amounts (millions) to force the case that used to split "RD$ / 1,274,490".
  await page.route('**/api/summary?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: {
        ...body,
        income_cents: 345678901,
        total_cents: 127449012,
        net_cents: 218229889,
        regular_total_cents: 127449012,
        one_offs_cents: 9876543,
        usd_cents: 6137512,
      },
    })
  })
  for (const width of [1440, 1232, 1000, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`/reports?month=${MONTH}`)
    const values = page.getByText(/^(RD|US)\$ [\d,.]+$/)
    await expect(values.first()).toBeVisible()
    const lines = await values.evaluateAll((els) =>
      els.map((el) => {
        const box = el.getBoundingClientRect()
        const lineHeight = parseFloat(getComputedStyle(el).lineHeight)
        const card = el.parentElement!.getBoundingClientRect()
        return { text: el.textContent, oneLine: box.height < lineHeight * 1.5, fits: box.right <= card.right }
      }),
    )
    for (const line of lines) expect(line, `${width}px: ${line.text}`).toMatchObject({ oneLine: true, fits: true })
  }
  // A summary request still in flight must not outlive the test (it would fail the next one).
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test.describe('corrections', () => {
  test.describe.configure({ mode: 'serial' })

  test('correcting a transaction moves the amount to another category', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    await page.getByRole('button', { name: /CAFE FICTICIO/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel(t('transactions.filters.category')).selectOption(HEALTH)
    await detail.getByLabel(t('transactions.detail.onlyThis')).check()
    await detail.getByRole('button', { name: t('transactions.save') }).click()

    await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()
    await expect(page.getByRole('button', { name: /CAFE FICTICIO/ })).toContainText(
      t('transactions.badge.corrected'),
    )

    await page.goto(`/reports?month=${MONTH}`)
    const categories = page.getByRole('region', { name: t('summary.categories.title') })
    await expect(categories.getByRole('link', { name: literal(HEALTH) })).toContainText('300')
    // Restaurants went down from 2,150 to 1,850.
    await expect(categories.getByRole('link', { name: literal(RESTAURANTS) })).toContainText('1,850')
  })

  test('correcting a deposit to the own-transfer category takes it out of income', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${MONTH}&kind=income`)
    await expect(page.getByRole('main')).toContainText(
      t('transactions.totals.income', { amount: 'RD$ 102,001' }),
    )
    await expect(page.getByRole('button', { name: /DEPOSITO CLIENTE/ })).toContainText(
      '+RD$ 12,000',
    )
    await page.getByRole('button', { name: /DEPOSITO CLIENTE/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel(t('transactions.filters.category')).selectOption(OWN_TRANSFER)
    await detail.getByLabel(t('transactions.detail.onlyThis')).check()
    await detail.getByRole('button', { name: t('transactions.save') }).click()

    await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()
    await expect(detail).toContainText(t('transactions.detail.notInList'))
    const list = page.getByRole('region', { name: LIST })
    await expect(list.getByRole('button', { name: /DEPOSITO CLIENTE/ })).toHaveCount(0)
    await expect(page.getByRole('main')).toContainText(
      t('transactions.totals.income', { amount: 'RD$ 90,001' }),
    )

    await page.goto(`/reports?month=${MONTH}`)
    await expect(page.getByRole('region', { name: KPIS })).toContainText(
      kpi(t('summary.kpi.income'), 'RD\\$\\s*90,001'),
    )
  })

  test('marking a one-off expense adds it to the one-offs figure', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    await page.getByRole('button', { name: /GASOLINERA FICTICIA/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel(t('transactions.detail.oneOff')).check()
    await detail.getByRole('button', { name: t('transactions.save') }).click()
    await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()

    await page.goto(`/reports?month=${MONTH}`)
    await expect(page.getByRole('region', { name: KPIS })).toContainText(
      kpi(t('summary.kpi.oneOffs'), 'RD\\$\\s*2,400'),
    )
  })
})

test('transactions: the Kind = Income filter leaves only the credits that are income', async ({
  page,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await page.getByRole('search').getByLabel(t('transactions.filters.kind')).selectOption(
    t('transactions.kind.income'),
  )

  await expect(page).toHaveURL(/kind=income/)
  const list = page.getByRole('region', { name: LIST })
  await expect(list.getByRole('button', { name: /DEPOSITO NOMINA/ })).toBeVisible()
  await expect(list.getByRole('button', { name: /CAFE FICTICIO|RETIRO CAJERO|SU PAGO/ })).toHaveCount(
    0,
  )
  const rows = await list.getByRole('button').all()
  expect(rows.length).toBeGreaterThan(0)
  for (const row of rows) await expect(row).toContainText(t('transactions.badge.income'))
  // Income goes with "+" and positive, not as a refund.
  await expect(list.getByRole('button', { name: /DEPOSITO NOMINA/ })).toContainText('+RD$ 85,000')
  // No spending in the list: the header shows no spending total, only the income.
  const header = page.getByRole('main').locator('header')
  const count = templateSource(message('transactions.count').other, { count: '\\d+' })
  const income = templateSource(message('transactions.totals.income'), { amount: 'RD\\$ [\\d,]+' })
  await expect(header).toContainText(new RegExp(`${count} · ${income}$`))
  await expect(header).not.toContainText('RD$ 0')
})

test('transactions: rows that are not spending show their kind', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}`)
  const list = page.getByRole('region', { name: LIST })
  const income = t('transactions.badge.income')
  const transfer = t('transactions.badge.transfer')
  await expect(list.getByRole('button', { name: /PAGO TARJETA/ })).toContainText(transfer)
  await expect(list.getByRole('button', { name: /RETIRO CAJERO/ })).not.toContainText(
    new RegExp(`${escapeRegExp(income)}|${escapeRegExp(transfer)}`),
  )
})

test.describe('compact list', () => {
  const list = (page: Page) => page.getByRole('region', { name: LIST })
  const rows = (page: Page) => list(page).locator('button[data-fingerprint]')

  test('rows take one line: more fit on the same screen', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`/transactions?month=${MONTH}`)
    await expect(rows(page).first()).toBeVisible()
    const heights = await rows(page).evaluateAll((els) =>
      els.map((el) => el.getBoundingClientRect().height),
    )
    expect(heights.length).toBe(22)
    for (const height of heights) expect(height).toBeLessThanOrEqual(52)
    // The original in US$ goes next to the amount in RD$, on the same line.
    const row = list(page).getByRole('button', { name: /TIENDA ONLINE/ })
    await expect(row).toContainText(/US\$ 30\.00\s*RD\$ 1,902/)
  })

  test('the detail and the day header stay in view while scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 700 })
    await page.goto(`/transactions?month=${MONTH}`)
    // A day with two rows, far from the end so the page can bring it to the top.
    const day = list(page).getByRole('group', { name: TUESDAY_JAN_20 })
    await day.evaluate((el) => {
      el.scrollIntoView({ block: 'start' })
      window.scrollBy(0, 30)
    })
    const header = await day.locator('[data-day-header]').boundingBox()
    expect(Math.abs(header!.y)).toBeLessThanOrEqual(1)

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await list(page).getByRole('button', { name: /CAFE FICTICIO/ }).click()
    const detail = page.getByRole('complementary')
    await expect(detail.getByRole('heading', { name: /CAFE FICTICIO/ })).toBeInViewport()
    const box = await detail.boundingBox()
    expect(box!.y).toBeGreaterThanOrEqual(0)
    expect(box!.y).toBeLessThan(700)
  })

  test('group by category: closed groups with their total; opening shows the rows', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    await page.getByRole('search').getByLabel(t('transactions.filters.groupBy')).selectOption(
      t('transactions.group.category'),
    )
    await expect(page).toHaveURL(/group=category/)

    const toggles = list(page).getByRole('button', { expanded: false })
    await expect(toggles.first()).toBeVisible()
    await expect(rows(page)).toHaveCount(0)
    // The category with the most spending goes first: Others, 4 purchases.
    const four = t('transactions.count', { count: 4 })
    await expect(toggles.first()).toHaveText(
      new RegExp(`^${OTHERS}\\s*${escapeRegExp(`${four} · RD$ 6,600`)}$`),
    )

    await toggles.first().click()
    const others = list(page).getByRole('button', { name: literal(`${OTHERS} ${four}`, { start: true }) })
    await expect(others).toHaveAttribute('aria-expanded', 'true')
    await expect(rows(page)).toHaveCount(4)
    for (const row of await rows(page).all()) await expect(row).toContainText(OTHERS)

    await others.press('Enter')
    await expect(others).toHaveAttribute('aria-expanded', 'false')
    await expect(rows(page)).toHaveCount(0)
  })

  test('sort by amount: within each day, the largest first', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    await page.getByRole('search').getByLabel(t('transactions.filters.sort')).selectOption(
      t('transactions.sort.amount'),
    )
    await expect(page).toHaveURL(/sort=amount/)
    const day = list(page).getByRole('group', { name: MONDAY_JAN_5 })
    const names = await day.locator('button[data-fingerprint]').allInnerTexts()
    expect(names.map((n) => n.split('\n')[0])).toEqual([
      'SU PAGO',
      'TRANSFERENCIA RECIBIDA',
      'TIENDA ONLINE',
      'STREAMING FICTICIO',
    ])
  })

  test('group by merchant and sort by amount live in the URL', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}&group=merchant&sort=amount`)
    await expect(page.getByRole('search').getByLabel(t('transactions.filters.groupBy'))).toHaveValue(
      'merchant',
    )
    await expect(page.getByRole('search').getByLabel(t('transactions.filters.sort'))).toHaveValue(
      'amount',
    )
    const payments = list(page).getByRole('button', { name: /^SU PAGO/ })
    await expect(payments).toHaveAttribute('aria-expanded', 'false')
    await payments.click()
    await expect(rows(page)).toHaveCount(2)
  })

  test('at 390 px: two lines per row and no sideways scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const route of [
      `/transactions?month=${MONTH}`,
      `/transactions?month=${MONTH}&group=category&sort=amount`,
    ]) {
      await page.goto(route)
      const toggle = list(page).getByRole('button', { expanded: false }).first()
      if (route.includes('group')) await toggle.click()
      await expect(rows(page).first()).toBeVisible()
      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width, route).toBeLessThanOrEqual(390)
      for (const height of await rows(page).evaluateAll((els) =>
        els.map((el) => el.getBoundingClientRect().height),
      ))
        expect(height, route).toBeLessThanOrEqual(64)
    }
  })
})

test('accounts: picking another card changes the panel heading', async ({ page }) => {
  await page.goto('/accounts')
  const heading = page.getByRole('region', { name: /···/ }).getByRole('heading', { level: 2 })
  const before = await heading.innerText()

  const other = before.includes('VISA DEMO') ? 'MC BLACK' : 'VISA DEMO'
  await page.getByRole('button', { name: new RegExp(other) }).click()

  await expect(heading).toContainText(other)
  await expect(page).toHaveURL(/account=/)
})

test('accounts: the statements table fits without horizontal scrolling at 1232 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1232, height: 961 })
  // The card with interest shows the verdict under the balance: it must fit too.
  for (const route of ['/accounts', INTEREST_CARD_PAGE]) {
    await page.goto(route)
    const box = page.getByRole('region', { name: t('accounts.table.label') })
    await expect(box).toBeVisible()
    const overflow = await box.evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(overflow, route).toBeLessThanOrEqual(0)
  }
})

test.describe('interest', () => {
  test("accounts: payment strip and what was left of December's statement", async ({ page }) => {
    // The made-up due date (22 Feb 2026) has passed: the strip says it is overdue.
    await page.goto(INTEREST_CARD_PAGE)
    const panel = page.getByRole('region', { name: /MASTERCARD FICTICIA/ })
    await expect(panel).toContainText(
      t('summary.interest.payOverdue', { amounts: 'RD$ 7,637', day: FEB_22 }),
    )
    await expect(panel).toContainText(t('summary.interest.minimum', { amounts: 'RD$ 380' }))
    const table = page.getByRole('region', { name: t('accounts.table.label') })
    const leftOver = escapeRegExp(t('summary.interest.leftOver', { amount: 'RD$ 6,150' }))
    const charged = escapeRegExp(t('summary.interest.charged', { amount: 'RD$ 287' }))
    await expect(table.getByRole('row').filter({ hasText: '28 dic' })).toContainText(
      new RegExp(`${leftOver}\\s*${charged}`),
    )
    await expect(table.getByRole('row').filter({ hasText: '28 nov' })).toContainText(
      t('summary.interest.paidFull'),
    )
    await expect(page.getByRole('button', { name: /MASTERCARD FICTICIA/ })).toContainText(
      t('summary.interest.noteOverdue', { amounts: 'RD$ 7,637', day: FEB_22 }),
    )
  })

  test('accounts: before the due date the strip says "before"', async ({ page }) => {
    // The screen compares with the browser's date.
    await page.clock.setFixedTime(new Date('2026-02-15T12:00:00'))
    await page.goto(INTEREST_CARD_PAGE)
    await expect(page.getByRole('region', { name: /MASTERCARD FICTICIA/ })).toContainText(
      t('summary.interest.pay', { amounts: 'RD$ 7,637', day: FEB_22 }),
    )
  })

  test("summary: the year's interest and the next payment link to Accounts", async ({ page }) => {
    // The server only gives the next payment if it is due today or later; the made-up dates
    // have passed, so it is added here on top of the real response.
    await page.route('**/api/interest**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: {
          ...body,
          next_due: {
            key: 'ficticio:credit_card',
            label: 'MASTERCARD FICTICIA ···5151',
            due_date: '2026-02-22',
            amounts: [{ currency: 'DOP', cents: 763740 }],
            minimums: [{ currency: 'DOP', cents: 38000 }],
            text: '',
          },
        },
      })
    })
    await page.goto(`/reports?month=${MONTH}`)
    const card = page.getByRole('region', { name: t('summary.interestCard.title') })
    await expect(card).toContainText(t('summary.interestCard.yearTitle', { year: 2026 }))
    await expect(card).toContainText('RD$ 287')
    await expect(card).toContainText('MASTERCARD FICTICIA ···5151')

    await card
      .getByRole('link', {
        name: literal(t('summary.interest.next', { amounts: 'RD$ 7,637', day: FEB_22 })),
      })
      .click()
    await expect(page).toHaveURL(/\/accounts\?account=ficticio%3Acredit_card$/)
    await expect(
      page.getByRole('region', { name: /···/ }).getByRole('heading', { level: 2 }),
    ).toContainText('MASTERCARD FICTICIA')
  })

  test('summary: a year without interest says so', async ({ page }) => {
    await page.goto('/reports?month=2025-12')
    const card = page.getByRole('region', { name: t('summary.interestCard.title') })
    await expect(card).toContainText(t('summary.interestCard.yearTitle', { year: 2025 }))
    await expect(card).toContainText(t('summary.interestCard.noInterest'))
  })
})

test.describe('recurring', () => {
  test.describe.configure({ mode: 'serial' })

  test('lists the recurring charges; «Not recurring» dismisses one and «Undo» brings it back', async ({
    page,
  }) => {
    const GYM = 'GIMNASIO FICTICIO'
    await page.goto('/recurring')
    await expect(page.getByRole('heading', { level: 1, name: t('recurring.title') })).toBeVisible()
    const streaming = page.getByRole('listitem').filter({ hasText: 'STREAMING FICTICIO' })
    await expect(streaming).toContainText(t('recurring.badge.rose'))
    await expect(page.getByRole('listitem').filter({ hasText: GYM })).toBeVisible()

    const mark = t('recurring.row.markNamed', { name: GYM })
    await page.getByRole('button', { name: mark }).click()
    await page
      .getByRole('group', { name: t('recurring.actions.label', { name: GYM }) })
      .getByRole('button', { name: t('recurring.actions.notRecurring') })
      .click()

    const dismissed = page.getByRole('region', { name: t('recurring.dismissed.label') })
    await dismissed.getByRole('button', { name: t('recurring.dismissed.title', { count: 1 }) }).click()
    await expect(dismissed).toContainText(GYM)
    await expect(page.getByRole('button', { name: mark })).toHaveCount(0)

    await dismissed.getByRole('button', { name: t('recurring.dismissed.undoNamed', { name: GYM }) }).click()
    await expect(page.getByRole('button', { name: mark })).toBeVisible()
    await expect(page.getByRole('region', { name: t('recurring.dismissed.label') })).toHaveCount(0)
  })

  test('summary of February 2026: «Upcoming» warns about the increase and leads to Recurring', async ({
    page,
  }) => {
    await page.goto('/?month=2026-02')
    const card = page.locator('[data-card="upcoming"]')
    await expect(card).toContainText(PRICE_UP)
    await card.getByRole('link', { name: t('home.upcoming.title') }).click()
    await expect(page).toHaveURL(/\/recurring$/)
    await expect(page.getByRole('heading', { level: 1, name: t('recurring.title') })).toBeVisible()
  })
})

test.describe('suggested one-off expenses (in «To review»)', () => {
  test.describe.configure({ mode: 'serial' })
  // February 2026 has a large, rare made-up purchase (AGENCIA FICTICIA, RD$ 45,000).
  const FEBRUARY = '2026-02'
  const card = (page: Page) => page.getByRole('region', { name: literal(t('summary.review.title')) })
  const openLabel = (merchant: string) =>
    literal(`${before(message('summary.oneOffs.openLabel'), 'merchant')}${merchant}`)

  test('transactions: the suggested row shows the question badge and the detail says why', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    const list = page.getByRole('region', { name: LIST })
    await expect(list.getByRole('button', { name: /AGENCIA FICTICIA/ })).toContainText(
      t('transactions.badge.suggestedOneOff'),
    )
    await expect(list.getByRole('button', { name: /CINE INVENTADO/ })).not.toContainText(
      t('transactions.badge.oneOff'),
    )

    await list.getByRole('button', { name: /AGENCIA FICTICIA/ }).click()
    const detail = page.getByRole('complementary')
    await expect(detail).toContainText(NEW_MERCHANT)
    await expect(detail.getByRole('button', { name: t('transactions.oneOff.dismiss') })).toBeVisible()
  })

  test('summary: the card fits in 390 px', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/review?month=${FEBRUARY}`)
    await expect(card(page)).toContainText(
      new RegExp(`${escapeRegExp(t('summary.review.title'))} \\(\\d+\\)`),
    )
    await expect(card(page)).toContainText(t('review.kind.oneOff'))
    await expect(card(page)).toContainText('RD$ 45,000')
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width).toBeLessThanOrEqual(390)
  })

  test('summary: at 390 px the name takes one line; day and account below', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/review?month=${FEBRUARY}`)
    const link = card(page).getByRole('link', { name: openLabel('AGENCIA FICTICIA') })
    await expect(card(page)).toContainText('6 feb · VISA DEMO ···4242')
    const name = link.getByTitle(/AGENCIA FICTICIA/)
    const lines = await name.evaluate((el) => {
      const style = getComputedStyle(el)
      return Math.round(el.getBoundingClientRect().height / parseFloat(style.lineHeight))
    })
    expect(lines).toBe(1)
  })

  test('summary: the suggestion opens the purchase in Transactions; Back returns', async ({
    page,
  }) => {
    await page.goto(`/review?month=${FEBRUARY}`)
    await card(page).getByRole('link', { name: openLabel('AGENCIA FICTICIA') }).click()
    await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${FEBRUARY}&tx=`))
    const detail = page.getByRole('complementary')
    await expect(detail.getByRole('heading', { name: /AGENCIA FICTICIA/ })).toBeVisible()
    await expect(detail).toContainText(NEW_MERCHANT)

    await page.goBack()
    await expect(page).toHaveURL(new RegExp(`/review\\?month=${FEBRUARY}$`))
    await expect(card(page)).toContainText('AGENCIA FICTICIA')
  })

  test('summary: «Not a one-off» removes it; «Suggest again» brings it back', async ({ page }) => {
    await page.goto(`/review?month=${FEBRUARY}`)
    await expect(card(page)).toContainText('AGENCIA FICTICIA')
    await card(page)
      .getByRole('button', { name: t('summary.oneOffs.dismissLabel', { merchant: 'AGENCIA FICTICIA' }) })
      .click()
    await expect(card(page)).not.toContainText('AGENCIA FICTICIA')
    // The button is not part of the link: it does not leave the Summary.
    await expect(page).toHaveURL(new RegExp(`/review\\?month=${FEBRUARY}$`))

    await page.goto(`/transactions?month=${FEBRUARY}`)
    const list = page.getByRole('region', { name: LIST })
    const row = list.getByRole('button', { name: /AGENCIA FICTICIA/ })
    await expect(row).not.toContainText(t('transactions.badge.oneOff'))
    await row.click()
    const detail = page.getByRole('complementary')
    await detail.getByRole('button', { name: t('transactions.oneOff.restore') }).click()
    await expect(row).toContainText(t('transactions.badge.suggestedOneOff'))
    await expect(detail.getByRole('button', { name: t('transactions.oneOff.dismiss') })).toBeVisible()
  })

  test('summary: «It is a one-off» moves it to the one-offs figure', async ({ page }) => {
    await page.goto(`/reports?month=${FEBRUARY}`)
    const kpis = page.getByRole('region', { name: KPIS })
    await expect(kpis).toContainText(kpi(t('summary.kpi.oneOffs'), 'RD\\$\\s*0'))
    await page.goto(`/review?month=${FEBRUARY}`)
    await card(page)
      .getByRole('button', {
        name: t('summary.oneOffs.confirmLabel', { merchant: 'AGENCIA FICTICIA' }),
        exact: true,
      })
      .click()
    await expect(card(page)).not.toContainText('AGENCIA FICTICIA')
    await expect(page).toHaveURL(new RegExp(`/review\\?month=${FEBRUARY}$`))
    await expect(card(page)).toContainText('DEPOSITO CAMBIO FICTICIO')
    await page.goto(`/reports?month=${FEBRUARY}`)
    await expect(kpis).toContainText(kpi(t('summary.kpi.oneOffs'), 'RD\\$\\s*45,000'))
  })
})

test.describe('to review', () => {
  test.describe.configure({ mode: 'serial' })
  const FEBRUARY = '2026-02'
  const card = (page: Page) => page.getByRole('region', { name: literal(t('summary.review.title')) })

  test('summary: gathers unusual income, large transfers and price increases', async ({ page }) => {
    await page.goto(`/review?month=${FEBRUARY}`)
    await expect(card(page)).toContainText(t('review.kind.unusualIncome'))
    await expect(card(page)).toContainText('DEPOSITO CAMBIO FICTICIO')
    await expect(card(page)).toContainText(t('review.kind.largeThirdParty'))
    await expect(card(page)).toContainText('RD$ 63,700')
    await expect(card(page)).toContainText('US$ 1,000.00')
    await expect(card(page)).toContainText(
      PRICE_UP,
    )
    // The separate one-off suggestions card is not there.
    await expect(card(page)).not.toContainText(
      before(message('summary.oneOffs.cardTitle'), 'count').replace(/\s*\($/, ''),
    )
  })

  test('summary: with only the VISA, the card ones remain', async ({ page }) => {
    await page.goto(`/review?month=${FEBRUARY}&accounts=demo%3Acredit_card`)
    await expect(card(page)).toContainText('STREAMING FICTICIO')
    await expect(card(page)).not.toContainText('DEPOSITO CAMBIO FICTICIO')
  })

  test('summary: «✓ Reviewed» removes it and it does not come back on reload', async ({ page }) => {
    await page.goto(`/review?month=${FEBRUARY}`)
    await card(page)
      .getByRole('button', { name: t('summary.review.reviewedLabel', { merchant: 'STREAMING FICTICIO' }) })
      .click()
    await expect(card(page)).not.toContainText('STREAMING FICTICIO')
    await page.reload()
    await expect(card(page)).toContainText('DEPOSITO CAMBIO FICTICIO')
    await expect(card(page)).not.toContainText('STREAMING FICTICIO')
  })

  test('summary: the transaction opens its detail in Transactions', async ({ page }) => {
    await page.goto(`/review?month=${FEBRUARY}`)
    const label = `${before(message('review.openLabel'), 'merchant')}DEPOSITO CAMBIO FICTICIO`
    await card(page).getByRole('link', { name: literal(label) }).click()
    await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${FEBRUARY}&tx=`))
    await expect(page.getByRole('complementary').getByRole('heading', { name: /DEPOSITO CAMBIO/ })).toBeVisible()
  })
})

test('bank accounts with a short name in Transactions and in «By account»', async ({ page }) => {
  // The made-up checking account is stored with its full bank name (FULL).
  const FULL = 'FICTICIO Cuenta corriente 777-0' // spanish-data
  const checking = t('accounts.bankType.checking')
  await page.goto('/transactions?month=2026-01')
  const row = page
    .getByRole('region', { name: LIST })
    .getByRole('button', { name: /RETIRO CAJERO/ })
  await expect(row).toContainText(new RegExp(`${escapeRegExp(checking)}\\s*···7770`))
  await expect(row).not.toContainText(FULL)
  await expect(row.getByTitle(FULL).first()).toBeAttached()

  await page.goto('/reports?month=2026-01')
  const byAccount = page.getByRole('region', { name: t('summary.byAccount.title') })
  await expect(byAccount.getByRole('link', { name: literal(`${checking} ···7770`) })).toHaveAttribute(
    'title',
    FULL,
  )
})

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  for (const route of [
    '/',
    `/?month=${MONTH}`,
    '/?month=2026-02',
    '/transactions',
    `/transactions?month=${MONTH}&kind=income`,
    '/recurring',
    '/accounts',
    '/categories',
    INTEREST_CARD_PAGE,
  ]) {
    test(`${route}: the bar goes to the bottom and the page does not scroll sideways`, async ({
      page,
    }) => {
      await page.goto(route)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

      // The menu is a bar fixed at the bottom of the screen; the content starts at the top.
      const nav = await page.getByRole('navigation', { name: t('shell.nav.label') }).boundingBox()
      const main = await page.getByRole('main').boundingBox()
      expect(nav).not.toBeNull()
      expect(main).not.toBeNull()
      expect(nav!.y + nav!.height).toBeCloseTo(844, 0)
      expect(main!.y).toBeLessThan(nav!.y)

      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width).toBeLessThanOrEqual(390)
    })
  }
})

test.describe('chosen accounts', () => {
  const VISA = 'VISA DEMO ···4242'
  // The picker button: its label, then the chosen accounts in parentheses.
  const PICKER = literal(before(message('shell.accounts.pick'), 'label').replace(/\s*\($/, ''), {
    start: true,
  })

  async function openPicker(page: Page) {
    await page.getByRole('button', { name: PICKER }).click()
    return page.getByRole('dialog')
  }

  test('one card: the KPIs change and Transactions shows only that card', async ({ page }) => {
    await page.goto(`/reports?month=${MONTH}`)
    const kpis = page.getByRole('region', { name: KPIS })
    const spending = kpi(t('summary.kpi.spending'), 'RD\\$\\s*18,573')
    await expect(kpis).toContainText(spending)

    // From "All", leave only the VISA DEMO: the others get unchecked.
    const dialog = await openPicker(page)
    for (const box of await dialog.getByRole('checkbox').all()) {
      const label = await box.evaluate((el) => el.closest('label')?.textContent ?? '')
      if (label.includes(VISA)) continue
      await box.click()
      await expect(box).not.toBeChecked()
    }
    // The last one cannot be removed, and it says so.
    await expect(dialog.getByRole('checkbox', { name: VISA })).toBeDisabled()
    await expect(dialog.getByRole('checkbox', { name: VISA })).toHaveAccessibleDescription(
      t('shell.accounts.lastHint'),
    )
    await page.keyboard.press('Escape')

    await expect(page).toHaveURL(/accounts=demo%3Acredit_card/)
    await expect(page.getByRole('button', { name: PICKER })).toContainText(VISA)
    await expect(
      page.getByText(t('months.headerScope', { last: 31, month: JANUARY, scope: VISA })),
    ).toBeVisible()
    await expect(kpis).not.toContainText(spending)
    await expect(kpis).toContainText(kpi(t('summary.kpi.net'), '—'))
    await expect(kpis).toContainText(t('summary.noFlow'))
    const byAccount = page.getByRole('region', { name: t('summary.byAccount.title') }).getByRole('link')
    await expect(byAccount).toHaveCount(1)
    await expect(byAccount).toContainText(VISA)

    await page.getByRole('region', { name: t('summary.categories.title') }).getByRole('link').first().click()
    await expect(page).toHaveURL(/accounts=demo%3Acredit_card/)
    const rows = page.getByRole('region', { name: LIST }).getByRole('button')
    await expect(rows.first()).toBeVisible()
    for (const row of await rows.all()) await expect(row).toContainText(/VISA DEMO\s*···4242/)

    // It is remembered: the Summary without parameters keeps the VISA; "All" removes it.
    await page.goto('/')
    await expect(page.getByRole('button', { name: PICKER })).toContainText(VISA)
    await (await openPicker(page)).getByRole('button', { name: t('shell.accounts.all') }).click()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: PICKER })).toContainText(
      t('shell.accounts.buttonAll'),
    )
    await page.reload()
    await expect(page.getByRole('button', { name: PICKER })).toContainText(
      t('shell.accounts.buttonAll'),
    )
  })

  test('only bank accounts: no interest and with the line of what was paid to your cards', async ({
    page,
  }) => {
    await page.goto(`/reports?month=${MONTH}`)
    await expect(page.getByRole('region', { name: t('summary.interestCard.title') })).toBeVisible()
    await page.getByRole('button', { name: PICKER }).click()
    await page.getByRole('dialog').getByRole('button', { name: t('shell.accounts.banksOnly') }).click()
    await page.keyboard.press('Escape')

    // The checking one, the seed's savings one and the savings one of the pending exchanges (of
    // 8 with the cash box, which is not a bank account).
    await expect(page.getByRole('button', { name: PICKER })).toContainText(
      t('shell.accounts.buttonSome', { count: 3, total: 8 }),
    )
    const kpis = page.getByRole('region', { name: KPIS })
    await expect(kpis).toContainText(
      new RegExp(templateSource(message('summary.ownMoves.toCards'), { amount: 'RD\\$\\s*11,000' })),
    )
    await expect(page.getByRole('region', { name: t('summary.interestCard.title') })).toHaveCount(0)
    // ATM and loan of the checking account; the card payment is not spending. (Income is not
    // looked at: another test corrects a deposit in the same database.)
    await expect(kpis).toContainText(kpi(t('summary.kpi.spending'), 'RD\\$\\s*7,000'))
  })

  test('an old link with ?account= still filters Transactions', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}&account=ficticio%3Achecking%3A777-0`)
    await expect(page.getByRole('button', { name: PICKER })).toContainText(
      `${t('accounts.bankType.checking')} ···7770`,
    )
    const rows = page.getByRole('region', { name: LIST }).getByRole('button')
    await expect(rows.first()).toBeVisible()
    for (const row of await rows.all()) await expect(row).toContainText('···7770')
  })

  test('at 390 px the open picker does not scroll the page sideways', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const route of [`/?month=${MONTH}`, `/transactions?month=${MONTH}`]) {
      await page.goto(route)
      await page.getByRole('button', { name: PICKER }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width, route).toBeLessThanOrEqual(390)
      const box = await page.getByRole('dialog').boundingBox()
      expect(box!.x, route).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width, route).toBeLessThanOrEqual(390)
      await page.keyboard.press('Escape')
    }
  })

  test('a selection that arrives in the URL is remembered: the menu takes it to Transactions', async ({
    page,
  }) => {
    await page.goto(`/?month=${MONTH}&accounts=demo%3Acredit_card`)
    await expect(page.getByRole('button', { name: PICKER })).toContainText(VISA)
    await page
      .getByRole('navigation', { name: t('shell.nav.label') })
      .getByRole('link', { name: t('shell.nav.transactions') })
      .click()
    await expect(page.getByRole('heading', { level: 1, name: t('transactions.title') })).toBeVisible()
    await expect(page.getByRole('button', { name: PICKER })).toContainText(VISA)
  })

  test('Recurring: «Upcoming» carries the accounts and the screen uses the same picker', async ({
    page,
  }) => {
    await page.goto('/recurring')
    const all = await page.locator('main header').first().innerText()
    await page.goto(`/?month=${MONTH}&accounts=demo%3Acredit_card`)
    await page
      .locator('[data-card="upcoming"]')
      .getByRole('link', { name: t('home.upcoming.title') })
      .click()
    await expect(page).toHaveURL(/\/recurring\?accounts=demo%3Acredit_card/)
    await expect(page.getByRole('button', { name: PICKER })).toContainText(VISA)
    await expect(page.getByText('STREAMING FICTICIO').first()).toBeVisible()
    await expect(page.locator('main header').first()).not.toHaveText(all)
  })
})

test.describe('editable categories', () => {
  test.describe.configure({ mode: 'serial' })
  const FEBRUARY = '2026-02'

  test('creating a car-care category with the word TALLER moves the garage purchase', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    await expect(page.getByRole('button', { name: /TALLER FICTICIO/ })).toContainText(OTHERS)

    await page.getByRole('link', { name: t('shell.nav.categories') }).click()
    await page.getByRole('button', { name: t('categories.new') }).click()
    const create = page.getByRole('dialog', { name: t('categories.new') })
    await create.getByLabel(t('categories.form.name')).fill(CAR_CARE)
    await create.getByRole('button', { name: t('categories.create') }).click()
    await expect(create).toBeHidden()

    const row = page.getByRole('listitem', { name: CAR_CARE })
    await expect(row).toContainText(t('categories.countYear', { count: 0 }))
    await expect(row.getByTitle(literal(t('categories.autoColor')))).toBeVisible()
    await row
      .getByRole('button', { name: t('categories.keywordsOf', { name: CAR_CARE }), exact: true })
      .click()
    const words = page.getByRole('dialog', { name: literal(t('categories.keywords')) })
    await words.getByLabel(literal(t('categories.keywordsDialog.label'))).fill('taller')
    await expect(words.getByRole('status')).toContainText(
      t('categories.preview.moves', { count: 1, money: 'RD$ 1,500' }),
    )
    await words.getByRole('button', { name: t('common.save') }).click()
    await expect(words).toBeHidden()
    await expect(row).toContainText(t('categories.keywordsLine', { words: 'TALLER' }))

    await page.goto(`/transactions?month=${FEBRUARY}`)
    await expect(page.getByRole('button', { name: /TALLER FICTICIO/ })).toContainText(CAR_CARE)
  })

  test('«+ New category…» in the detail creates it and leaves it chosen', async ({ page }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    await page.getByRole('button', { name: /CINE INVENTADO/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel(t('transactions.filters.category')).selectOption(
      t('transactions.filters.newCategory'),
    )
    const create = page.getByRole('dialog', { name: t('categories.new') })
    await expect(create.getByLabel(t('categories.form.kind'))).toHaveValue('expense') // the row's kind
    await create.getByLabel(t('categories.form.name')).fill(CINEMA)
    await create.getByRole('button', { name: t('categories.create') }).click()
    await expect(create).toBeHidden()

    await expect(detail.getByLabel(t('transactions.filters.category'))).toHaveValue(CINEMA)
    await detail.getByRole('button', { name: t('transactions.save') }).click()
    await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()
    await expect(page.getByRole('button', { name: /CINE INVENTADO/ })).toContainText(CINEMA)
  })

  test('a hidden category is not offered when correcting', async ({ page }) => {
    await page.goto('/categories')
    const row = page.getByRole('listitem', { name: CINEMA })
    await row.getByRole('button', { name: t('categories.hideNamed', { name: CINEMA }), exact: true }).click()
    await expect(row).toContainText(t('categories.hidden'))
    await expect(
      row.getByRole('button', { name: t('categories.showNamed', { name: CINEMA }), exact: true }),
    ).toBeVisible()

    await page.goto(`/transactions?month=${FEBRUARY}`)
    await page.getByRole('button', { name: /TALLER FICTICIO/ }).click()
    const select = page.getByRole('complementary').getByLabel(t('transactions.filters.category'))
    await expect(select.locator(`option[value="${CINEMA}"]`)).toHaveCount(0)
    await expect(select.locator(`option[value="${CAR_CARE}"]`)).toHaveCount(1)
  })
})

test.describe('shared expenses from a transaction, and notes', () => {
  test.describe.configure({ mode: 'serial' })
  // February 2026: a RD$ 3,000 dinner on the VISA DEMO. Everything written here is undone at the
  // end (through the log), so the other specs find the made-up data as it was.
  const FEBRUARY = '2026-02'
  const DINNER = 'RESTAURANTE COMPARTIDO'
  const GROUP = 'Cena del equipo' // spanish-data
  const NEW_PERSON = 'Ana Ficticia' // spanish-data
  let mark = 0

  test.beforeAll(async ({ request }) => {
    mark = await logMark(request)
  })

  test.afterAll(async ({ request }) => {
    await undoSince(request, mark)
  })

  test('«Share…» goes straight to «I paid it» with it; a new group from there keeps the draft', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    const list = page.getByRole('region', { name: LIST })
    const dinner = list.getByRole('button', { name: new RegExp(DINNER) })
    await dinner.click()
    const detail = page.getByRole('complementary')
    await detail
      .getByRole('region', { name: t('shared.tx.title') })
      .getByRole('button', { name: t('shared.tx.share') })
      .click()

    const sheet = page.getByRole('dialog', { name: t('shared.add.mine') })
    await expect(sheet).toContainText(DINNER)
    await sheet.getByRole('button', { name: t('shared.add.newGroup') }).click()
    const create = page.getByRole('dialog', { name: t('shared.newGroup.title') })
    await create.getByLabel(t('shared.newGroup.name')).fill(GROUP)
    const search = create.getByLabel(t('shared.newGroup.search'))
    await search.fill(NEW_PERSON)
    await create.getByRole('button', { name: t('shared.people.createNamed', { name: NEW_PERSON }) }).click()
    await search.fill('Lu')
    await create.getByRole('list', { name: t('shared.people.suggestions') }).getByRole('button', { name: /^Luis/ }).click()
    await create.getByRole('button', { name: t('shared.newGroup.create') }).click()
    await expect(create).toHaveCount(0)

    // Back in the draft: the new group is chosen and the split is equal among the three.
    await expect(sheet.getByRole('button', { name: GROUP })).toHaveAttribute('aria-pressed', 'true')
    await expect(sheet.getByTestId('split-summary')).toHaveText(
      t('shared.add.splitEqual', { count: 3, amount: 'RD$ 1,000' }),
    )
    await sheet.getByRole('button', { name: t('shared.add.save') }).click()
    await expect(sheet).toHaveCount(0)

    await expect(dinner).toContainText(t('links.badge.shared'))
    await expect(dinner).toContainText(t('links.badge.owed', { amount: 'RD$ 2,000' }))
    await expect(detail.getByTestId('link-summary-shared')).toHaveText(
      t('shared.tx.entryPending', { group: GROUP, share: 'RD$ 1,000', pending: 'RD$ 2,000' }),
    )
    await detail.getByRole('link', { name: t('shared.tx.openGroup') }).click()
    await expect(page).toHaveURL(/\/shared\/\d+$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(GROUP)
    await expect(page.getByTestId('group-sentence')).toHaveText(
      t('shared.group.sentence.owed', { amount: 'RD$ 2,000' }),
    )
  })

  test('Pending lists the group and opens its page; Transactions filters the shared ones with something pending', async ({
    page,
  }) => {
    await page.goto('/pending')
    const owed = page.getByRole('region', { name: t('pending.figure.owed') })
    const row = owed.getByRole('link', { name: new RegExp(GROUP) })
    await expect(row).toContainText('RD$ 2,000')
    await row.click()
    await expect(page).toHaveURL(/\/shared\/\d+$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(GROUP)

    await page.goto(`/transactions?month=${FEBRUARY}&shared=pending`)
    const rows = page.getByRole('region', { name: LIST }).getByRole('button')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(DINNER)
    await page.getByRole('button', { name: t('transactions.filters.removeShared') }).click()
    await expect(page).not.toHaveURL(/shared=/)
  })

  test('removing it from the group leaves the detail with the offer again', async ({ page }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    const list = page.getByRole('region', { name: LIST })
    const dinner = list.getByRole('button', { name: new RegExp(DINNER) })
    await dinner.click()
    const detail = page.getByRole('complementary')
    await detail.getByRole('button', { name: t('shared.tx.remove') }).click()
    await expect(detail.getByTestId('link-summary-shared')).toHaveText(t('shared.tx.offer'))
    await expect(dinner).not.toContainText(t('links.badge.shared'))
  })

  test('a note is saved, marked on the row and found by the search', async ({ page }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    const list = page.getByRole('region', { name: LIST })
    await list.getByRole('button', { name: new RegExp(DINNER) }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel(t('transactions.detail.note')).fill(DINNER_NOTE)
    await detail.getByRole('button', { name: t('transactions.save'), exact: true }).click()
    await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()
    const dinner = list.getByRole('button', { name: new RegExp(DINNER) })
    await expect(dinner.getByRole('img', { name: t('transactions.list.hasNote') })).toBeVisible()

    await page.goto(`/transactions?month=${FEBRUARY}&q=luis`)
    await expect(list.getByRole('button')).toHaveCount(1)
    await expect(list.getByRole('button').first()).toContainText(DINNER)
  })
})

test.describe('currency exchanges', () => {
  test.describe.configure({ mode: 'serial' })
  // February 2026: a RD$ 63,700 deposit on the 12th, a US$ 1,000 transfer on the 13th (rate
  // 63.70) and another of US$ 61.67 on the 14th.
  const FEBRUARY = '2026-02'

  /** The exchange line: its sides, its rate and its status, joined with " · ". */
  function exchangeLine(sides: string, rate: string, status: string): string {
    return [t('links.exchange.line', { sides }), t('links.exchange.rate', { rate }), status].join(' · ')
  }

  async function openDeposit(page: Page) {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    await page.getByRole('button', { name: /DEPOSITO CAMBIO/ }).click()
    await page
      .getByRole('complementary')
      .getByRole('region', { name: t('links.summary.exchangeTitle') })
      .getByRole('button', { name: t('links.action.manage') })
      .click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/DEPOSITO CAMBIO/)
  }

  test('the suggestion links the deposit and the transfer; the agreed rate leaves something pending', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${FEBRUARY}`)
    const list = page.getByRole('region', { name: LIST })
    const deposit = list.getByRole('button', { name: /DEPOSITO CAMBIO/ })
    await expect(deposit).toContainText(t('links.badge.suggestedExchange'))
    await deposit.click()
    const detail = page.getByRole('complementary')
    await expect(detail).toContainText(
      t('links.shortcut.exchange', {
        what: t('links.linkedLabel', {
          merchant: 'TRANSFERENCIA A PERSONA FICTICIA',
          day: t('months.longDay', { day: 13, month: FEBRUARY_NAME }),
        }),
      }),
    )
    await detail.getByRole('button', { name: t('links.shortcut.pair') }).click()
    await expect(detail.getByTestId('link-summary-exchange')).toHaveText(
      t('links.summary.exchangeNoPending'),
    )
    await expect(detail.getByLabel(t('transactions.filters.category'))).toBeDisabled()
    await expect(detail).toContainText(t('transactions.detail.locked'))
    // The row now shows the system category of a linked exchange.
    await expect(deposit).toContainText(CURRENCY_EXCHANGE)
    await expect(list.getByRole('button', { name: /TRANSFERENCIA A PERSONA/ })).toContainText(
      t('links.badge.exchange'),
    )

    await openDeposit(page)
    await expect(page.getByTestId('exchange-line')).toHaveText(
      exchangeLine('RD$ 63,700 ↔ US$ 1,000.00', '63.70', t('links.exchange.noPending')),
    )
    await expect(page.getByText(t('links.exchange.needsRate'))).toBeVisible()
    await page.getByLabel(t('links.exchange.agreedRate'), { exact: true }).fill('60')
    await page.getByRole('button', { name: t('links.exchange.saveRate') }).click()
    await expect(page.getByTestId('exchange-line')).toHaveText(
      exchangeLine(
        'RD$ 63,700 ↔ US$ 1,000.00',
        '60.00',
        t('links.exchange.pendingConverted', { amount: 'US$ 61.67', dop: 'RD$ 3,700' }),
      ),
    )

    // You were paid first: you owe it, at the agreed rate.
    await page.goto('/pending')
    const owed = page.getByRole('region', { name: t('pending.figure.owe') }).getByRole('link', {
      name: /DEPOSITO CAMBIO/,
    })
    await expect(owed).toContainText('US$ 61.67')
    await expect(owed).toContainText(
      `${t('pending.approx', { amount: 'RD$ 3,700' })} ${t('pending.agreedRate', { rate: '60.00' })}`,
    )
  })

  test('adding a leg from the screen: only what fits in the pending amount', async ({ page }) => {
    await openDeposit(page)
    const legs = page.getByRole('group', { name: t('links.exchange.candidates') })
    // US$ 61.67 is left to send: neither the TOKE DE in RD$ nor anything larger is offered.
    await expect(legs.getByRole('checkbox')).toHaveCount(1)
    await legs.getByRole('checkbox', { name: /TRANSFERENCIA SALDO PERSONA/ }).check()
    await page.getByRole('button', { name: t('links.exchange.pair') }).click()
    await expect(page.getByTestId('exchange-line')).toHaveText(
      exchangeLine('RD$ 63,700 ↔ US$ 1,061.67', '60.00', t('links.exchange.noPending')),
    )
    await expect(page.getByRole('list', { name: t('links.exchange.legs') })).toContainText(
      'TRANSFERENCIA SALDO PERSONA',
    )

    await page.getByRole('link', { name: t('links.page.back') }).click()
    await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${FEBRUARY}&tx=`))
    const deposit = page
      .getByRole('region', { name: LIST })
      .getByRole('button', { name: /DEPOSITO CAMBIO/ })
    await expect(deposit).toHaveAttribute('aria-pressed', 'true')
    await expect(deposit).toBeInViewport()
  })

  test('«Exchange complete» closes it and the pending amount leaves Pending', async ({ page }) => {
    await openDeposit(page)
    await page.getByRole('button', { name: t('links.exchange.close') }).click()
    await expect(page.getByTestId('exchange-line')).toHaveText(
      new RegExp(`· ${escapeRegExp(t('links.exchange.closed'))}$`),
    )
    await page.goto('/pending')
    await expect(page.getByRole('region', { name: t('pending.figure.owe') })).not.toContainText(
      'DEPOSITO CAMBIO',
    )
  })

  test("a screen opened directly goes back to the transaction's month", async ({ page }) => {
    await openDeposit(page)
    const url = page.url()
    await page.goto(url)
    await page.getByRole('link', { name: t('links.page.back') }).click()
    await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${FEBRUARY}&tx=`))
  })
})

test('transactions: arriving with a chosen row, the list brings it into view', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 420 })
  await page.goto('/transactions?month=2026-02')
  const list = page.getByRole('region', { name: LIST })
  const last = list.locator('[data-fingerprint]').last()
  const fingerprint = await last.getAttribute('data-fingerprint')
  await expect(last).not.toBeInViewport()

  await page.goto(`/transactions?month=2026-02&tx=${fingerprint}`)
  const row = list.locator(`[data-fingerprint="${fingerprint}"]`)
  await expect(row).toHaveAttribute('aria-pressed', 'true')
  await expect(row).toBeInViewport({ ratio: 1 })
})

test('transactions: on the phone, closing the detail leaves the chosen row in view', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 })
  await page.goto('/transactions?month=2026-02')
  const list = page.getByRole('region', { name: LIST })
  const last = list.locator('[data-fingerprint]').last()
  const fingerprint = await last.getAttribute('data-fingerprint')
  await expect(last).not.toBeInViewport()

  await page.goto(`/transactions?month=2026-02&tx=${fingerprint}`)
  // The phone's detail covers the screen; «Back» closes it.
  await page.getByRole('button', { name: t('transactions.detail.back') }).click()
  await expect(page.getByRole('button', { name: t('transactions.detail.back') })).toBeHidden()
  const row = list.locator(`[data-fingerprint="${fingerprint}"]`)
  await expect(row).toBeInViewport({ ratio: 1 })
})

test('links saved before the English rename open the new pages', async ({ page }) => {
  await page.goto(`/transacciones?mes=${MONTH}&cuentas=ficticio%3Acredit_card`) // spanish-data: pre-rename link
  await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${MONTH}&accounts=ficticio%3Acredit_card$`))
  await page.goto('/bitacora') // spanish-data: pre-rename link
  await expect(page).toHaveURL(/\/log$/)
})
