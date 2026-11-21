import { expect, test, type Page } from '@playwright/test'
import { LOCALE } from '../src/i18n'
import { escapeRegExp, literal, t } from './text'

// The month in detail (Reports, `?month=`) and the review list, with the made-up data of
// tests/e2e_server.py. February 2026 brings four
// warnings in «To review»; January 2026, none. What is missing to test (more categories, more
// warnings, a long analysis) is added on top of the real response.
const FEBRUARY = '2026-02'
const JANUARY = '2026-01'

// Where a value goes inside a catalog message, to match it with a pattern.
const HOLE = '\u0000'

/** The catalog `text` (with HOLE where a value goes) as an anchored RegExp, `source` in the hole. */
function withHole(text: string, source: string): RegExp {
  return new RegExp(`^${text.split(HOLE).map(escapeRegExp).join(source)}$`)
}

/** "2026-02" → month name and year as the app writes it in phrases (Intl, lowercase). */
function monthPhrase(month: string): string {
  const name = new Intl.DateTimeFormat(LOCALE, { month: 'long', timeZone: 'UTC' }).format(
    new Date(`${month}-01T00:00:00Z`),
  )
  return `${name} ${month.slice(0, 4)}`
}

const reviewCard = (page: Page) =>
  page.getByRole('region', { name: literal(t('summary.review.title')) })
const categoriesCard = (page: Page) =>
  page.getByRole('region', { name: t('summary.categories.title') })
const readingCard = (page: Page) =>
  page.getByRole('region', { name: t('summary.reading.title') })

/** Made-up warnings: other tests mark February's as reviewed on the same database. */
function reviewItems(count: number) {
  return Array.from({ length: count }, (_, n) => ({
    kind: n % 2 === 0 ? 'large_third_party' : 'one_off',
    fingerprint: `made-up-fingerprint-${n + 1}`,
    day: '2026-02-13',
    month: FEBRUARY,
    merchant: `COMERCIO INVENTADO ${n + 1}`,
    description: `COMERCIO INVENTADO ${n + 1} SANTIAGO`,
    account_label: 'FICTICIO Cuenta corriente 777-0', // spanish-data
    amount_cents: 6_370_000,
    currency: 'DOP',
    amount_dop_cents: null,
    // The backend's reason text.
    reason: 'Transferencia a terceros de RD$ 63,700 (desde RD$ 25,000 se revisa)', // spanish-data
    reviewed: false,
  }))
}

async function fakeReview(page: Page, count: number) {
  await page.route('**/api/review?**', (route) => route.fulfill({ json: reviewItems(count) }))
}

test.describe('the review list and the categories table', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('the Summary counts what is to review; its list shows every item and «See less» folds it', async ({
    page,
  }) => {
    await fakeReview(page, 7)
    await page.goto(`/?month=${FEBRUARY}`)
    const count = page.locator('[data-card="review"]')
    await expect(count.getByTestId('review-count')).toHaveText(t('home.review.count', { count: 7 }))
    await expect(count).toContainText('COMERCIO INVENTADO 1')
    await count.getByRole('link', { name: t('home.review.title') }).click()
    await expect(page).toHaveURL(`/review?month=${FEBRUARY}`)
    const card = reviewCard(page)
    await expect(card).toContainText(t('review.cardTitle', { count: 7 }))
    await expect(card.getByRole('listitem')).toHaveCount(7)
    await expect(card).toContainText('COMERCIO INVENTADO 7')
    const less = card.getByRole('button', { name: t('summary.review.seeLess') })
    await expect(less).toHaveAttribute('aria-expanded', 'true')
    await less.click()
    await expect(card.getByRole('listitem')).toHaveCount(4)
  })

  test('Categories shows the top 8 by spending and «See the N» expands the rest', async ({
    page,
  }) => {
    await page.route('**/api/summary?**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const extra = Array.from({ length: 8 }, (_, n) => ({
        ...body.categories[0],
        category: `Made-up ${n + 1}`,
        amount_cents: 1_000 + n,
      }))
      await route.fulfill({ response, json: { ...body, categories: [...body.categories, ...extra] } })
    })
    await page.goto(`/reports?month=${FEBRUARY}`)
    const categories = categoriesCard(page)
    await expect(categories.getByRole('link')).toHaveCount(8)
    const more = categories.getByRole('button', {
      name: withHole(t('summary.categories.seeAll', { count: HOLE }), '\\d+'),
    })
    const prefix = t('summary.categories.seeAll', { count: HOLE }).split(HOLE)[0]
    const total = Number((await more.textContent())!.replace(prefix, ''))
    expect(total).toBeGreaterThan(8)
    await more.click()
    await expect(categories.getByRole('link')).toHaveCount(total)
  })
})

test.describe('month reading', () => {
  test('tabs only with content; the arrows change tabs and «Read more» opens', async ({
    page,
  }) => {
    const long = Array.from({ length: 8 }, (_, n) => `Made-up paragraph number ${n + 1}.`).join(
      '\n\n',
    )
    await page.route(`**/api/insights/${FEBRUARY}`, (route) =>
      route.fulfill({
        json: {
          month: FEBRUARY,
          label: 'Febrero 2026', // spanish-data: the API's month label
          text: long,
          accounts: null,
          created_at: '2026-03-02T10:00:00',
          updated_at: '2026-03-02T10:00:00',
          stale: false,
        },
      }),
    )
    await page.route('**/api/summary?**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const changes = [
        {
          category: 'Made-up trips',
          diff_cents: 4_000_000,
          one_offs_cents: 0,
          purchases: 1,
          habitual_purchases: 0,
        },
      ]
      await route.fulfill({ response, json: { ...body, changes } })
    })
    await page.goto(`/reports?month=${FEBRUARY}`)
    const card = readingCard(page)
    const tabs = card.getByRole('tab')
    const insightTab = card.getByRole('tab', { name: t('summary.reading.tab.insight') })
    const changesTab = card.getByRole('tab', { name: t('summary.reading.tab.changes') })
    // February is not atypical: there is no «What happened».
    await expect(tabs).toHaveText([
      t('summary.reading.tab.insight'),
      t('summary.reading.tab.changes'),
    ])
    await expect(insightTab).toHaveAttribute('aria-selected', 'true')

    // Collapsed: the end of the analysis is not seen until «Read more».
    const panel = card.getByRole('tabpanel')
    await expect(panel.getByText('Made-up paragraph number 8.')).not.toBeInViewport()
    await panel.getByRole('button', { name: t('summary.reading.readMore') }).click()
    await expect(panel.getByText('Made-up paragraph number 8.')).toBeVisible()
    await expect(
      panel.getByRole('button', { name: t('summary.reading.readLess') }),
    ).toHaveAttribute('aria-expanded', 'true')

    await panel.getByRole('button', { name: t('summary.reading.readLess') }).click()
    // With the keyboard, entering the collapsed part opens it.
    await panel.getByRole('link', { name: t('summary.insight.editInReports') }).focus()
    await expect(panel.getByRole('button', { name: t('summary.reading.readLess') })).toBeVisible()

    await insightTab.focus()
    await page.keyboard.press('End')
    await expect(changesTab).toBeFocused()
    await page.keyboard.press('Home')
    await expect(insightTab).toBeFocused()
    await page.keyboard.press('ArrowRight')
    await expect(changesTab).toBeFocused()
    await expect(changesTab).toHaveAttribute('aria-selected', 'true')
    await expect(panel).toContainText('Made-up trips')
    await expect(panel).toHaveAttribute('tabindex', '0')
  })

  test('with nothing to read, one line offers to copy the command', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto(`/reports?month=${JANUARY}`)
    const card = readingCard(page)
    await expect(card).toContainText(t('summary.insight.noReading'))
    await expect(card.getByRole('tab')).toHaveCount(0)
    const command = `michelito analysis ${JANUARY}`
    const copy = card.getByRole('button', {
      name: t('summary.insight.copyCommandLabel', { command }),
    })
    await copy.click()
    await expect(copy).toHaveText(t('summary.insight.copied'))
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(command)
  })
})

/** Twelve made-up months: July and August atypical (neighbours) and December with two marks. */
async function twelveMonths(page: Page) {
  await page.route('**/api/summary?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    const months = Array.from({ length: 12 }, (_, n) => {
      const at = 2025 * 12 + 2 + n // March 2025 … February 2026
      return `${Math.floor(at / 12)}-${String((at % 12) + 1).padStart(2, '0')}`
    })
    // The API's short month labels.
    const labels = ['mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic', 'ene', 'feb'] // spanish-data
    const trend = months.map((month, n) => ({
      month,
      label: labels[n],
      total_cents: 2_000_000 + n * 50_000,
      income_cents: 8_000_000,
      partial: n === 11,
      spent_flag: n === 4 || n === 9 ? 'up' : null,
      spent_habitual_cents: 1_500_000,
      income_flag: n === 5 ? 'down' : n === 9 ? 'up' : null,
      income_habitual_cents: 6_000_000,
    }))
    await route.fulfill({ response, json: { ...body, trend } })
  })
}

type Box = { x: number; y: number; width: number; height: number }

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

const monthsList = (page: Page) =>
  page.getByRole('list', { name: t('summary.trendBars.monthsLabel') })

test.describe('last 12 months', () => {
  for (const width of [1440, 1024, 390]) {
    test(`${width} px: the marks of atypical months neither collide nor leave their month`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 })
      await twelveMonths(page)
      await page.goto(`/reports?month=${FEBRUARY}`)
      const chart = page.getByRole('region', { name: t('summary.trendBars.title') })
      const marks = chart.getByTestId('trend-mark')
      await expect(marks).toHaveCount(4)
      const boxes = await marks.evaluateAll((els) =>
        els.map((el) => {
          const box = el.getBoundingClientRect()
          const column = el.closest('button')!.getBoundingClientRect()
          return {
            box: { x: box.x, y: box.y, width: box.width, height: box.height },
            inside: box.left >= column.left - 0.5 && box.right <= column.right + 0.5,
          }
        }),
      )
      for (const [i, mark] of boxes.entries()) {
        expect(mark.inside, `mark ${i} inside its month`).toBe(true)
        for (const other of boxes.slice(i + 1)) expect(overlaps(mark.box, other.box)).toBe(false)
      }
      if (width === 1440) {
        // With room, the marks say what happened; the month with two has them stacked.
        await expect(marks.nth(0)).toHaveText(`▲ ${t('summary.flag.spentHigh')}`)
        await expect(marks.nth(1)).toHaveText(`▼ ${t('summary.flag.incomeLow')}`)
      }
    })
  }

  test('390 px: the detail of each month stays inside the screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await twelveMonths(page)
    await page.goto(`/reports?month=${FEBRUARY}`)
    const columns = monthsList(page).getByRole('button')
    for (const index of [0, 5, 11]) {
      await columns.nth(index).focus()
      const tip = page.getByTestId('trend-tip')
      await expect(tip).toBeVisible()
      const box = (await tip.boundingBox())!
      expect(box.x, `month ${index + 1}`).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width, `month ${index + 1}`).toBeLessThanOrEqual(390)
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(scroll).toBeLessThanOrEqual(390)
    }
  })

  test('tapping the chosen month shows and hides its detail', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await twelveMonths(page)
    await page.goto(`/reports?month=${FEBRUARY}`)
    const chosen = monthsList(page).getByRole('button', {
      name: literal(monthPhrase(FEBRUARY), { start: true }),
    })
    await expect(chosen).toHaveAttribute('aria-current', 'true')
    await chosen.click()
    await expect(page.getByTestId('trend-tip')).toBeVisible()
    await chosen.click()
    await expect(page.getByTestId('trend-tip')).toHaveCount(0)
    await expect(page).toHaveURL(new RegExp(`month=${FEBRUARY}`))
  })
})

test.describe('month reading: why there are no changes', () => {
  test('month in progress: it compares once the accounts close', async ({ page }) => {
    await page.goto(`/reports?month=${JANUARY}`)
    await expect(readingCard(page)).toContainText(t('summary.reading.changes.partial'))
  })

  test('no complete earlier month: one is needed to compare', async ({ page }) => {
    await page.goto('/reports?month=2025-12')
    await expect(readingCard(page)).toContainText(t('summary.reading.changes.notComparable'))
  })

  test('with a usual amount and no changes: everything within the usual', async ({ page }) => {
    await page.route('**/api/summary?**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, habitual_cents: 2_000_000, changes: [] } })
    })
    await page.goto('/reports?month=2025-12')
    await expect(readingCard(page)).toContainText(t('summary.reading.changes.withinUsual'))
  })

  test('when the analysis does not load, it says so and lets you retry', async ({ page }) => {
    let calls = 0
    await page.route(`**/api/insights/${JANUARY}`, (route) => {
      calls += 1
      return route.fulfill({ status: 500, json: { detail: 'made-up failure' } })
    })
    await page.goto(`/reports?month=${JANUARY}`)
    const card = readingCard(page)
    await expect(card).toContainText(t('summary.reading.loadError'))
    // The start of the «no reading yet» line, as before: no part of it shows.
    const noReadingStart = t('summary.insight.noReading').split(' ').slice(0, 4).join(' ')
    await expect(card).not.toContainText(noReadingStart)
    const before = calls
    await card.getByRole('button', { name: t('summary.reading.retry') }).click()
    await expect.poll(() => calls).toBeGreaterThan(before)
  })
})

test.describe('Categories amounts', () => {
  // A big category with a one-off expense and a new one (no spending in earlier months): the
  // widest figures the row can show.
  const BIG = 'Made-up vehicle and fuel'
  const FRESH = 'Made-up new one'

  async function wideCategories(page: Page) {
    await page.route('**/api/summary?**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const base = body.categories[0]
      const big = {
        ...base,
        category: BIG,
        amount_cents: 15_082_700,
        habitual_cents: 245_000,
        diff_cents: 14_837_700,
        same: false,
        one_offs_cents: 12_000_000,
      }
      const fresh = { ...base, category: FRESH, amount_cents: 7_547_600 }
      const isNew = { habitual_cents: 0, diff_cents: 7_547_600, same: false, one_offs_cents: 0 }
      const categories = [big, { ...fresh, ...isNew }, ...body.categories]
      await route.fulfill({ response, json: { ...body, categories } })
    })
  }

  for (const width of [1440, 1024, 390]) {
    test(`${width} px: amounts with RD$, «new» and nothing leaves the row`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await wideCategories(page)
      await page.goto(`/reports?month=${FEBRUARY}`)
      const categories = categoriesCard(page)
      const big = categories.getByRole('link', { name: literal(BIG) })
      await expect(big).toContainText('RD$ 150,827')
      await expect(big).toContainText(t('summary.diff.oneOff', { text: '+RD$ 148,377' }))
      await expect(categories.getByRole('link', { name: literal(FRESH) })).toContainText(
        new RegExp(`RD\\$ 75,476\\s*${escapeRegExp(t('summary.diff.new'))}`),
      )
      for (const row of await categories.getByRole('link').all()) {
        const fits = await row.evaluate((el) => el.scrollWidth <= el.clientWidth)
        expect(fits, (await row.textContent()) ?? '').toBe(true)
      }
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(scroll).toBeLessThanOrEqual(width)
      await page.screenshot({ path: `test-results/categories-${width}.png`, fullPage: false })
      await categories.screenshot({ path: `test-results/categories-card-${width}.png` })
    })
  }
})
