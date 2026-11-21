// The Summary as a stack of cards (projects `chromium` on a desktop and `mobile` at 390×844):
// the current month opens by default, each card leads to its list with the month and the
// accounts, «Back» returns to the same scroll, the invitations (at most two, dismissible) and a
// walk that fails if anything shown on a card cannot be tapped. Read-only: nothing is saved on
// the server (dismissed invitations live in the browser).
import { expect, test, type Page } from '@playwright/test'
import type { MonthOption } from '../src/lib/api'
import { LOCALE } from '../src/i18n'
import { t } from './text'

const NEWEST = '2026-02'
const CARD_ACCOUNT = 'demo%3Acredit_card'
const VISA_ACCOUNT = 'demo:credit_card'
const PRICE_UP = 'Subió de US$ 9.99 a US$ 11.99' // spanish-data: the backend's alert text

function card(page: Page, id: string) {
  return page.locator(`[data-testid="summary-cards"] [data-card="${id}"]`)
}

async function cardsReady(page: Page) {
  await expect(card(page, 'spending')).toBeVisible()
  await expect(card(page, 'categories')).toBeVisible()
  await expect(page.locator('[data-testid="summary-cards"] [aria-busy="true"]')).toHaveCount(0)
  await expect(page.locator('[data-testid="summary-cards"] [data-slot="skeleton"]')).toHaveCount(0)
}

test('the current month opens by default, live', async ({ page }) => {
  const months = (await (await page.request.get('/api/months')).json()) as MonthOption[]
  expect(months[0].month).toBe(NEWEST)
  expect(months[0].partial).toBe(true)
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText(months[0].label)
  await expect(page.getByTestId('coverage-pill')).toContainText(
    t('home.coverage.inProgress', { closed: 0, total: 4 }),
  )
  // The spending curve goes up to the server's today and marks it.
  await expect(card(page, 'spending').getByTestId('curve-today')).toBeVisible()
})

test('the coverage pill opens a sheet with each account', async ({ page }) => {
  await page.goto(`/?month=2025-12`)
  const pill = page.getByTestId('coverage-pill')
  await expect(pill).toHaveText(new RegExp(t('home.coverage.allClosed', { count: 4 })))
  await pill.click()
  const sheet = page.getByRole('dialog', { name: t('home.coverage.sheetTitle') })
  await expect(sheet.getByRole('listitem')).toHaveCount(4)
  // The month's scope lives here (not under the month on the Summary).
  const scope = t('months.headerScope', {
    last: 31,
    month: 'diciembre', // spanish-ui: month name built with Intl
    scope: t('common.allYourAccounts'),
  })
  await expect(sheet.getByTestId('coverage-scope')).toHaveText(scope)
  await expect(page.getByRole('main').getByText(scope)).toHaveCount(1)
  await expect(sheet).toContainText(t('summary.coverage.complete'))
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
})

test.describe('each card leads to the list that explains it', () => {
  test('spending, flow and to review keep the month and the accounts', async ({ page }) => {
    await page.goto(`/?month=2025-12&accounts=${CARD_ACCOUNT}`)
    await cardsReady(page)
    await card(page, 'spending').getByRole('link', { name: new RegExp(t('home.spending.title')) }).click()
    await expect(page).toHaveURL(`/transactions?month=2025-12&kind=expense&accounts=${CARD_ACCOUNT}`)
    await page.goBack()

    await card(page, 'review').getByRole('link', { name: t('home.review.title') }).click()
    await expect(page).toHaveURL(`/review?month=2025-12&accounts=${CARD_ACCOUNT}`)
    await expect(page.getByRole('region', { name: new RegExp(t('summary.review.title')) })).toBeVisible()
    await page.goBack()

    // Only cards chosen: no flow to show, but the card still leads to the month in Reports.
    await expect(card(page, 'flow')).toContainText(t('summary.noFlow'))
    await card(page, 'flow').getByRole('link', { name: new RegExp(t('home.flow.title')) }).click()
    await expect(page).toHaveURL(`/reports?month=2025-12&accounts=${CARD_ACCOUNT}`)
    await expect(
      page.getByRole('region', { name: t('summary.kpi.sectionLabel'), exact: true }),
    ).toBeVisible()
  })

  test('a latest transaction opens its detail; a category, its expenses in the month', async ({
    page,
  }) => {
    await page.goto(`/?month=${NEWEST}`)
    await cardsReady(page)
    const row = card(page, 'latest').getByRole('listitem').first().getByRole('link')
    const href = await row.getAttribute('href')
    expect(href).toMatch(new RegExp(`^/transactions\\?month=${NEWEST}&tx=`))
    await row.click()
    await expect(page).toHaveURL(href!)
    await page.goBack()

    const first = card(page, 'categories').getByRole('listitem').first().getByRole('link')
    const name = (await first.getAttribute('aria-label'))!.split(':')[0]
    await first.click()
    await expect(page).toHaveURL(
      `/transactions?${new URLSearchParams({ month: NEWEST, category: name, kind: 'expense' })}`,
    )
    await page.goBack()
    // A slice of the donut goes to the same place (the largest one starts at the top of the ring).
    const ring = card(page, 'categories').locator(`circle[data-slice="${name}"]`)
    const size = (await ring.boundingBox())!
    await ring.click({ position: { x: size.width / 2 + 8, y: 6 } })
    await expect(page).toHaveURL(
      `/transactions?${new URLSearchParams({ month: NEWEST, category: name, kind: 'expense' })}`,
    )
  })

  test('upcoming, shared and the budget invitation', async ({ page }) => {
    await page.goto(`/?month=${NEWEST}`)
    await cardsReady(page)
    await card(page, 'upcoming').getByRole('link', { name: t('home.upcoming.title') }).click()
    await expect(page).toHaveURL('/recurring')
    await page.goBack()
    await card(page, 'shared').getByRole('link', { name: t('home.shared.title') }).click()
    await expect(page).toHaveURL('/shared')
    await page.goBack()
    await card(page, 'invite-budget').getByRole('link', { name: new RegExp(t('home.invite.budget.action')) }).click()
    await expect(page).toHaveURL(`/budget?month=${NEWEST}`)
  })
})

const scrollY = (page: Page) => page.evaluate(() => Math.round(window.scrollY))

test.describe('«Back» returns to the Summary at the same scroll position', () => {
  // A short window, so the page scrolls a long way on a desktop too and the destinations are
  // shorter than the Summary's scroll (their scroll would be clamped).
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: page.viewportSize()!.width, height: 500 })
  })

  const targets: [string, (page: Page) => ReturnType<Page['locator']>][] = [
    ['a category row', (page) => card(page, 'categories').getByRole('listitem').first().getByRole('link')],
    ['the latest transactions title', (page) => card(page, 'latest').getByRole('link', { name: t('home.latest.title') })],
    ['the flow card', (page) => card(page, 'flow').getByRole('link', { name: new RegExp(t('home.flow.title')) })],
  ]
  for (const [what, target] of targets) {
    test(`from ${what}: the destination starts at the top`, async ({ page }) => {
      await page.goto(`/?month=${NEWEST}`)
      await cardsReady(page)
      // As far down as the page goes, then the target in the middle of the window (clear of the
      // phone's bottom bar, so the tap does not scroll the page first).
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
      await target(page).evaluate((el) => el.scrollIntoView({ block: 'center' }))
      const before = await scrollY(page)
      if (what !== 'the flow card') expect(before).toBeGreaterThan(150)
      await target(page).click()
      await expect(page).not.toHaveURL(/\/\?month=/)
      await expect.poll(() => scrollY(page)).toBe(0)
      await page.goBack()
      await expect(card(page, 'categories')).toBeVisible()
      await expect.poll(() => scrollY(page)).toBe(before)
    })
  }
})

test.describe('invitations', () => {
  // Nothing applies yet: no budget, no recurring charges and no groups.
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/shared', (route) =>
      route.fulfill({ json: { totals: [], people: [], groups: [] } }),
    )
    await page.route('**/api/recurring?**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, items: [], alerts: [] } })
    })
  })

  test('at most two, by usefulness; «×» dismisses one for good', async ({ page }) => {
    await page.goto(`/?month=${NEWEST}`)
    const invites = page.locator('[data-invitation]')
    await expect(invites).toHaveCount(2)
    await expect(invites.nth(0)).toHaveAttribute('data-invitation', 'budget')
    await expect(invites.nth(1)).toHaveAttribute('data-invitation', 'recurring')
    await expect(card(page, 'upcoming')).toHaveCount(0)
    await expect(card(page, 'shared')).toHaveCount(0)

    await page
      .getByRole('button', { name: t('home.invite.dismiss', { text: t('home.invite.budget.text') }) })
      .click()
    await expect(invites).toHaveCount(2)
    await expect(invites.nth(0)).toHaveAttribute('data-invitation', 'recurring')
    await expect(invites.nth(1)).toHaveAttribute('data-invitation', 'shared')

    await page.reload()
    await expect(invites).toHaveCount(2)
    await expect(page.locator('[data-invitation="budget"]')).toHaveCount(0)
    await page.locator('[data-invitation="shared"]').getByRole('link').click()
    await expect(page).toHaveURL('/shared?view=groups')
  })
})

test('every figure, category and account on the header and the cards can be tapped', async ({
  page,
}) => {
  for (const url of [`/?month=${NEWEST}`, '/?month=2025-12']) {
    await page.goto(url)
    await cardsReady(page)
    const loose = await page.evaluate(() => {
      // The month header (month, arrows, accounts, coverage pill) and every card.
      const roots = ['summary-header', 'summary-cards'].map(
        (id) => document.querySelector(`[data-testid="${id}"]`)!,
      )
      const found: string[] = []
      for (const start of roots) {
        const walker = document.createTreeWalker(start, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const text = node.textContent?.trim() ?? ''
          const parent = node.parentElement
          if (!text || !parent || parent.closest('[aria-hidden="true"], .sr-only')) continue
          parent.scrollIntoView({ block: 'center', inline: 'nearest' })
          const range = document.createRange()
          range.selectNodeContents(node)
          const box = range.getBoundingClientRect()
          if (box.width === 0 || box.height === 0) continue
          const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
          if (!hit?.closest('a, button')) found.push(text)
        }
      }
      return found
    })
    expect(loose, url).toEqual([])
  }
})

test('the spending card marks one-off expenses as dots that open them', async ({ page }) => {
  // December has no one-off expense marked: the made-up pace below adds one.
  await page.route('**/api/summary/pace?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: {
        ...body,
        one_offs: [{ fingerprint: 'made-up-fp', day: '2025-12-10', merchant: 'TIENDA FICTICIA', amount_cents: 500000 }], // spanish-data
      },
    })
  })
  await page.goto('/?month=2025-12')
  const dot = card(page, 'spending').locator('[data-one-off]')
  await expect(dot).toHaveCount(1)
  const box = (await dot.boundingBox())!
  expect(box.width).toBeGreaterThanOrEqual(44)
  await dot.click()
  await expect(page).toHaveURL('/transactions?month=2025-12&tx=made-up-fp')
})

test('desktop: three columns with «Month spending» across two', async ({ page, isMobile }) => {
  test.skip(isMobile, 'desktop layout')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/?month=${NEWEST}`)
  await cardsReady(page)
  const spending = (await card(page, 'spending').boundingBox())!
  const flow = (await card(page, 'flow').boundingBox())!
  expect(Math.abs(spending.y - flow.y)).toBeLessThan(2)
  expect(spending.width).toBeGreaterThan(flow.width * 1.8)
  const xs = await page
    .locator('[data-testid="summary-cards"] [data-card]')
    .evaluateAll((els) => [...new Set(els.map((el) => Math.round(el.getBoundingClientRect().x)))])
  expect(xs).toHaveLength(3)
  // No holes: the cards that start on the same row end on the same line too.
  const boxes = await page
    .locator('[data-testid="summary-cards"] > div')
    .evaluateAll((els) =>
      els.map((el) => {
        const box = el.getBoundingClientRect()
        return { top: Math.round(box.top), bottom: Math.round(box.bottom) }
      }),
    )
  for (const box of boxes) {
    const row = boxes.filter((other) => other.top === box.top)
    expect(new Set(row.map((other) => other.bottom)).size, `row at ${box.top}`).toBe(1)
  }
  // The invitation shown sits in its own row, across the whole width.
  const invitations = (await page.getByTestId('invitations').boundingBox())!
  const grid = (await page.getByTestId('summary-cards').boundingBox())!
  expect(Math.abs(invitations.width - grid.width)).toBeLessThan(2)
})

test('phone: swiping the header changes the month', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'touch gesture')
  await page.goto(`/?month=${NEWEST}`)
  await cardsReady(page)
  const header = page.getByTestId('summary-header')
  const box = (await header.boundingBox())!
  const swipe = async (fromX: number, toX: number) => {
    const y = box.y + 20
    await header.evaluate(
      (el, { fromX, toX, y }) => {
        const touch = (x: number) => new Touch({ identifier: 1, target: el, clientX: x, clientY: y })
        el.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: [touch(fromX)], changedTouches: [touch(fromX)] }))
        el.dispatchEvent(new TouchEvent('touchend', { bubbles: true, touches: [], changedTouches: [touch(toX)] }))
      },
      { fromX, toX, y },
    )
  }
  await swipe(100, 300) // the finger moves right: the previous month
  await expect(page).toHaveURL('/?month=2026-01')
  await swipe(300, 100) // and left: the next one
  await expect(page).toHaveURL('/?month=2026-02')
})

/** RD$ as the cards write it: whole units, «−» for negatives, a non-breaking space. */
function dop(cents: number): string {
  const whole = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 }).format(Math.abs(cents) / 100)
  return `${cents < 0 && whole !== '0' ? '−' : ''}RD$ ${whole}`
}

test('the figures on the cards are the API\'s', async ({ page }) => {
  for (const month of [NEWEST, '2025-12']) {
    const summary = await (await page.request.get(`/api/summary?month=${month}`)).json()
    const pace = await (await page.request.get(`/api/summary/pace?month=${month}`)).json()
    const shared = await (await page.request.get('/api/shared')).json()
    await page.goto(`/?month=${month}`)
    await cardsReady(page)
    // The hero is the month's total (provisional ones included), as far as the pace counts.
    await expect(page.getByTestId('spending-total')).toHaveText(dop(summary.total_cents))
    expect(pace.total_to_date_cents).toBe(summary.total_cents)
    const flow = card(page, 'flow')
    await expect(flow).toContainText(dop(summary.income_cents))
    await expect(flow).toContainText(dop(summary.income_cents - summary.net_cents))
    await expect(flow.getByTestId('flow-kept')).toHaveText(dop(summary.net_cents))
    const dopTotal = shared.totals.find((total: { currency: string }) => total.currency === 'DOP')
    await expect(card(page, 'shared').getByTestId('shared-owed')).toHaveText(
      dop(dopTotal.owed_to_me_cents),
    )
    await expect(card(page, 'shared').getByTestId('shared-owe')).toHaveText(dop(dopTotal.i_owe_cents))
  }
})

test('flow: income not in yet stays neutral; spending more than came in gets the dot', async ({
  page,
}) => {
  // More went out than came in (other specs change December's figures on the same database:
  // the month's own numbers are set here), with the income known only through 15 December or
  // complete.
  let through: string | null = '2025-12-15'
  await page.route('**/api/summary?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: { ...body, income_cents: 1_000_000, net_cents: -500_000, income_through: through },
    })
  })
  await page.goto('/?month=2025-12')
  const flow = card(page, 'flow')
  await expect(flow.getByTestId('flow-through')).toHaveText(
    t('summary.income.through', { day: '15 dic' }), // spanish-ui: short day built with Intl
  )
  await expect(flow.getByTestId('flow-kept')).toHaveText(dop(-500_000))
  await expect(flow.getByTestId('flow-overspent')).toHaveCount(0)
  through = null
  await page.reload()
  await expect(flow.getByTestId('flow-through')).toHaveCount(0)
  await expect(flow.getByTestId('flow-overspent')).toHaveAccessibleName(t('home.flow.overspent'))
})

test('«Upcoming» shows the recurring warnings and leads to Recurring', async ({ page }) => {
  await page.goto(`/?month=${NEWEST}`)
  const alerts = card(page, 'upcoming').getByTestId('upcoming-alerts')
  await expect(alerts).toContainText(t('home.upcoming.alerts', { count: 1 }))
  await expect(alerts).toContainText(PRICE_UP)
  await card(page, 'upcoming').getByRole('link', { name: t('home.upcoming.title') }).click()
  await expect(page).toHaveURL('/recurring')
})

test('«Shared» carries the Pending figures and leads there with the accounts', async ({ page }) => {
  for (const accounts of [null, VISA_ACCOUNT]) {
    const query = accounts ? `&accounts=${encodeURIComponent(accounts)}` : ''
    await page.goto(`/?month=${NEWEST}${query}`)
    const line = card(page, 'shared').getByTestId('shared-pending')
    await expect(line).toBeVisible()
    const text = (await line.textContent()) ?? ''
    await line.click()
    await expect(page).toHaveURL(
      accounts ? `/pending?accounts=${encodeURIComponent(accounts)}` : '/pending',
    )
    const owed = (await page.getByTestId('pending-owed').textContent())!.trim()
    const owe = (await page.getByTestId('pending-owe').textContent())!.trim()
    expect(text.replace(/ /g, ' ')).toBe(t('home.shared.pending', { owed, owe }))
  }
})

test('a card that does not load says so and retries', async ({ page }) => {
  let fail = true
  await page.route('**/api/review?**', (route) =>
    fail ? route.fulfill({ status: 500, json: { detail: 'made-up failure' } }) : route.fallback(),
  )
  await page.goto(`/?month=${NEWEST}`)
  const review = card(page, 'review')
  await expect(review.getByRole('alert')).toContainText(
    t('common.loadError', { what: t('home.what.review') }),
  )
  fail = false
  await review.getByRole('button', { name: t('common.retry') }).click()
  await expect(review.getByRole('alert')).toHaveCount(0)
  // Retrying stays on the Summary: the button sits above the card's link.
  await expect(page).toHaveURL(`/?month=${NEWEST}`)
})
