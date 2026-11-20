// The phone layout (projects `mobile` at 390×844 with touch and `mobile-360` at 360×740): bottom
// bar, Transactions (day headers, filter sheet, long-press), the full-screen detail with its sheets,
// Summary, Investments, Shared and no sideways scrolling on any main screen. Read-only but for one
// test that shares an expense and undoes it (through the log): whatever a test opens it closes without saving (the
// same spec runs at both widths on one database).
import { expect, test, type Locator, type Page } from '@playwright/test'
import type { Tx } from '../src/lib/api'
import { addEntry, createGroup, logMark, undoSince } from './ledger'
import { literal, t } from './text'

const MONTH = '2026-01'
const SATURDAY = 'sáb' // spanish-ui: short weekday built with Intl
const JANUARY = 'ene' // spanish-ui: short month built with Intl
const LIST = t('transactions.list.label')

function bar(page: Page): Locator {
  return page.locator('nav[data-bottom-bar]')
}

function sheet(page: Page, title: string): Locator {
  return page.getByRole('dialog', { name: title })
}

async function noSidewaysScroll(page: Page, what: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, what).toBeLessThanOrEqual(0)
}

async function monthItems(page: Page): Promise<Tx[]> {
  const response = await page.request.get(`/api/transactions?month=${MONTH}`)
  return ((await response.json()) as { items: Tx[] }).items
}

test.describe('bottom bar', () => {
  test('replaces the sidebar, stays at the bottom and leaves room under the content', async ({
    page,
  }) => {
    await page.goto('/')
    const nav = bar(page)
    await expect(nav).toBeVisible()
    await expect(page.getByRole('navigation', { name: t('shell.nav.label') })).toHaveCount(1)
    const viewport = page.viewportSize()!
    const box = (await nav.boundingBox())!
    expect(box.y + box.height).toBeCloseTo(viewport.height, 0)
    // Every button is a 44 px touch target.
    for (const item of await nav.locator('a, button').all()) {
      const itemBox = (await item.boundingBox())!
      expect(itemBox.height).toBeGreaterThanOrEqual(44)
    }
    // The active one is marked; the main content ends above the bar.
    await expect(nav.getByRole('link', { name: t('shell.nav.summary') })).toHaveAttribute(
      'aria-current',
      'page',
    )
    const padding = await page
      .getByRole('main')
      .evaluate((el) => parseFloat(getComputedStyle(el).paddingBottom))
    expect(padding).toBeGreaterThanOrEqual(box.height)
  })

  test('«More» opens a sheet with the other sections and marks itself active there', async ({
    page,
  }) => {
    await page.goto('/')
    const more = bar(page).getByRole('button', { name: t('shell.nav.more') })
    await more.click()
    const dialog = sheet(page, t('shell.nav.moreTitle'))
    await expect(dialog).toBeVisible()
    for (const key of [
      'shell.nav.budget',
      'shell.nav.pending',
      'shell.nav.recurring',
      'shell.nav.reports',
      'shell.nav.accounts',
      'shell.nav.categories',
      'shell.nav.log',
    ] as const) {
      await expect(dialog.getByRole('link', { name: t(key) })).toBeVisible()
    }
    // Escape closes it and focus returns to «More».
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(more).toBeFocused()

    await more.click()
    await sheet(page, t('shell.nav.moreTitle')).getByRole('link', { name: t('shell.nav.reports') }).click()
    await expect(page).toHaveURL(/\/reports$/)
    await expect(sheet(page, t('shell.nav.moreTitle'))).toHaveCount(0)
    await expect(more).toHaveAttribute('aria-current', 'page')
  })

  test('a tap outside the sheet closes it', async ({ page }) => {
    await page.goto('/')
    await bar(page).getByRole('button', { name: t('shell.nav.more') }).click()
    const dialog = sheet(page, t('shell.nav.moreTitle'))
    await expect(dialog).toBeVisible()
    await page.mouse.click(10, 10)
    await expect(dialog).toHaveCount(0)
  })
})

test.describe('transactions', () => {
  test('grouped by day with short sticky headers; search visible, filters in a sheet', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    const list = page.getByRole('region', { name: LIST })
    const header = list.locator('[data-day-header]').first()
    // The short header (weekday, day, month) rather than the long one.
    await expect(header).toHaveText(
      t('transactions.day.short', { weekday: SATURDAY, day: 31, month: JANUARY }),
    )
    await expect(header).toHaveCSS('position', 'sticky')

    const search = page.getByRole('searchbox')
    await expect(search).toBeVisible()
    await expect(page.getByRole('search').getByLabel(t('transactions.filters.kind'))).toHaveCount(0)

    await page.getByRole('button', { name: t('transactions.filters.open', { count: 0 }) }).click()
    const filters = sheet(page, t('transactions.filters.title'))
    await filters.getByLabel(t('transactions.filters.kind')).selectOption('income')
    await filters.getByRole('button', { name: t('transactions.filters.done') }).click()
    await expect(filters).toHaveCount(0)
    await expect(page).toHaveURL(/kind=income/)
    await expect(
      page.getByRole('button', { name: t('transactions.filters.open', { count: 1 }) }),
    ).toBeVisible()
    for (const row of await list.locator('[data-fingerprint]').all()) {
      await expect(row).toContainText(t('transactions.badge.income'))
    }
    await noSidewaysScroll(page, 'filtered list')
  })

  test('grouping by category stays available from the sheet', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    await page.getByRole('button', { name: t('transactions.filters.open', { count: 0 }) }).click()
    const filters = sheet(page, t('transactions.filters.title'))
    await filters.getByLabel(t('transactions.filters.groupBy')).selectOption('category')
    await filters.getByRole('button', { name: t('transactions.filters.done') }).click()
    await expect(page).toHaveURL(/group=category/)
    const list = page.getByRole('region', { name: LIST })
    await list.getByRole('button', { expanded: false }).first().click()
    await expect(list.locator('[data-fingerprint]').first()).toBeVisible()
  })

  test('holding a row enters «Select» with it chosen; the bar sits above the bottom bar', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    const list = page.getByRole('region', { name: LIST })
    const row = list.locator('[data-fingerprint]').nth(1)
    const fingerprint = await row.getAttribute('data-fingerprint')
    const box = (await row.boundingBox())!
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    const actions = page.getByRole('region', { name: t('transactions.selection.region') })
    await expect(actions).toBeVisible()
    await page.mouse.up()
    // The release does not uncheck it, nor open the detail.
    const checkbox = list.locator(`[data-fingerprint="${fingerprint}"] input[type="checkbox"]`)
    await expect(checkbox).toBeChecked()
    await expect(checkbox).toBeFocused()
    await expect(page.locator('[data-mobile-detail]')).toHaveCount(0)
    await expect(actions).toContainText(t('common.selection.count', { count: 1 }))

    const barBox = (await bar(page).boundingBox())!
    const actionsBox = (await actions.boundingBox())!
    expect(actionsBox.y + actionsBox.height).toBeLessThanOrEqual(barBox.y + 1)

    await page.keyboard.press('Escape')
    await expect(actions).toHaveCount(0)
  })

  test('a quick tap opens the detail full screen; «Back» returns to the list', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    const list = page.getByRole('region', { name: LIST })
    await list.locator('[data-fingerprint]').first().tap()
    const detail = page.locator('[data-mobile-detail]')
    await expect(detail).toBeVisible()
    const box = (await detail.boundingBox())!
    const viewport = page.viewportSize()!
    expect(box).toMatchObject({ x: 0, y: 0, width: viewport.width, height: viewport.height })
    await detail.getByRole('button', { name: t('transactions.detail.back') }).click()
    await expect(detail).toHaveCount(0)
    await expect(page).not.toHaveURL(/tx=/)
  })
})

test.describe('transaction detail', () => {
  test('header, three quick actions and only the actions that apply, each in a sheet', async ({
    page,
  }) => {
    const items = await monthItems(page)
    const expense = items.find((tx) => tx.kind === 'expense' && tx.link === '' && tx.can_share)!
    const income = items.find((tx) => tx.kind === 'income' && tx.link === '')!
    await page.goto(`/transactions?month=${MONTH}&tx=${expense.fingerprint}`)
    const detail = page.locator('[data-mobile-detail]')
    await expect(detail.getByRole('heading', { level: 2 })).toHaveText(expense.merchant)
    await expect(
      detail.getByRole('button', {
        name: t('transactions.detail.changeCategory', { category: expense.category }),
      }),
    ).toBeVisible()
    const quick = detail.getByRole('group', { name: t('transactions.actions.label') })
    await expect(quick.getByRole('button')).toHaveText([
      t('transactions.actions.category'),
      t('transactions.actions.note'),
      t('transactions.actions.share'),
    ])
    const more = detail.getByRole('region', { name: t('transactions.actions.more') })
    await expect(more.getByRole('button', { name: t('transactions.actions.oneOff') })).toBeVisible()
    await expect(more.getByRole('button', { name: t('transactions.actions.reimbursement') })).toHaveCount(0)

    // The category opens in a sheet (not inline) and closing it leaves the page as it was.
    await expect(detail.getByLabel(t('transactions.filters.category'), { exact: true })).toHaveCount(0)
    await quick.getByRole('button', { name: t('transactions.actions.category') }).click()
    const category = sheet(page, t('transactions.actions.category'))
    await expect(category.getByLabel(t('transactions.filters.category'))).toHaveValue(expense.category)
    await expect(category.getByRole('button', { name: t('transactions.save') })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(category).toHaveCount(0)
    await expect(detail).toBeVisible()

    await quick.getByRole('button', { name: t('transactions.actions.note') }).click()
    await expect(sheet(page, t('transactions.actions.note')).getByRole('textbox')).toBeVisible()
    await page.keyboard.press('Escape')

    await more.getByRole('button', { name: t('transactions.actions.history') }).click()
    await expect(sheet(page, t('transactions.actions.history'))).toBeVisible()
    await page.keyboard.press('Escape')

    // An income: no one-off, no sharing.
    await page.goto(`/transactions?month=${MONTH}&tx=${income.fingerprint}`)
    await expect(detail.getByRole('heading', { level: 2 })).toHaveText(income.merchant)
    await expect(more.getByRole('button', { name: t('transactions.actions.oneOff') })).toHaveCount(0)
    await expect(quick.getByRole('button', { name: t('transactions.actions.share') })).toHaveCount(0)
    await noSidewaysScroll(page, 'detail')
  })

  test('a linked transaction shows its link on top with «Open»', async ({ page }) => {
    const months = ['2026-02', MONTH, '2025-12']
    let linked: Tx | undefined
    for (const month of months) {
      const response = await page.request.get(`/api/transactions?month=${month}`)
      const items = ((await response.json()) as { items: Tx[] }).items
      linked = items.find((tx) => tx.link === 'exchange' || tx.link === 'shared')
      if (linked) break
    }
    test.skip(!linked, 'no linked transaction in the made-up data')
    const tx = linked!
    await page.goto(`/transactions?month=${tx.day.slice(0, 7)}&tx=${tx.fingerprint}`)
    const links = page.getByRole('region', { name: t('transactions.links.label') })
    const line = links.getByTestId(`mobile-link-${tx.link}`)
    await expect(line).toBeVisible()
    const title = tx.link === 'exchange' ? t('links.summary.exchangeTitle') : t('shared.tx.title')
    await line.getByRole('button', { name: t('transactions.links.openLabel', { what: title }) }).click()
    const kind = tx.link === 'exchange' ? 'transactions.actions.exchange' : 'transactions.actions.share'
    await expect(sheet(page, t(kind))).toBeVisible()
    await page.keyboard.press('Escape')
    // Already linked: it is not offered again in the list.
    const more = page.getByRole('region', { name: t('transactions.actions.more') })
    if (tx.link === 'exchange') {
      await expect(more.getByRole('button', { name: t('transactions.actions.exchange') })).toHaveCount(0)
    }
  })

  test('closing the detail leaves the chosen row fully in view', async ({ page }) => {
    await page.goto(`/transactions?month=2026-02`)
    const list = page.getByRole('region', { name: LIST })
    const last = list.locator('[data-fingerprint]').last()
    const fingerprint = await last.getAttribute('data-fingerprint')
    await page.goto(`/transactions?month=2026-02&tx=${fingerprint}`)
    await page.getByRole('button', { name: t('transactions.detail.back') }).click()
    await expect(page.locator('[data-mobile-detail]')).toHaveCount(0)
    await expect(list.locator(`[data-fingerprint="${fingerprint}"]`)).toBeInViewport({ ratio: 1 })
  })
})

test.describe('detail as a screen', () => {
  const detail = (page: Page) => page.locator('[data-mobile-detail]')

  test('the system back closes the detail and stays in the list, as it was', async ({ page }) => {
    await page.goto(`/transactions?month=2026-02&kind=expense`)
    const list = page.getByRole('region', { name: LIST })
    const last = list.locator('[data-fingerprint]').last()
    await last.scrollIntoViewIfNeeded()
    const fingerprint = await last.getAttribute('data-fingerprint')
    const before = await page.evaluate(() => window.scrollY)
    await last.click()
    await expect(detail(page)).toBeVisible()
    await expect(page).toHaveURL(/tx=/)
    // The rest of the app is out of reach while the detail covers it.
    await expect(page.locator('#root')).toHaveAttribute('inert', '')

    await page.goBack()
    await expect(detail(page)).toHaveCount(0)
    await expect(page).toHaveURL(/\/transactions\?month=2026-02&kind=expense$/)
    await expect(page.locator('#root')).not.toHaveAttribute('inert')
    const row = list.locator(`[data-fingerprint="${fingerprint}"]`)
    await expect(row).toBeInViewport({ ratio: 1 })
    await expect(row).toBeFocused()
    expect(Math.abs((await page.evaluate(() => window.scrollY)) - before)).toBeLessThan(2)
  })

  test('«Back» undoes the entry it added; a link straight to a row does not leave the app', async ({
    page,
  }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    const list = page.getByRole('region', { name: LIST })
    const row = list.locator('[data-fingerprint]').first()
    const fingerprint = await row.getAttribute('data-fingerprint')
    await row.click()
    await detail(page).getByRole('button', { name: t('transactions.detail.back') }).click()
    await expect(detail(page)).toHaveCount(0)
    await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${MONTH}$`))
    await expect(list.locator(`[data-fingerprint="${fingerprint}"]`)).toBeFocused()
    // Going forward again reopens it: the entry was really undone, not replaced.
    await page.goForward()
    await expect(detail(page)).toBeVisible()

    // Arriving with ?tx= (from the Summary, a bookmark): «Back» stays in Transactions.
    await page.goto('/')
    await page.goto(`/transactions?month=${MONTH}&tx=${fingerprint}`)
    await detail(page).getByRole('button', { name: t('transactions.detail.back') }).click()
    await expect(detail(page)).toHaveCount(0)
    await expect(page).toHaveURL(new RegExp(`/transactions\\?month=${MONTH}$`))
    await expect(list.locator(`[data-fingerprint="${fingerprint}"]`)).toBeFocused()
  })

  test('«See the whole merchant» closes the detail and shows the list with the row chosen', async ({
    page,
  }) => {
    const tx = (await monthItems(page)).find((item) => item.kind === 'expense')!
    await page.goto(`/transactions?month=${MONTH}`)
    await page.locator(`[data-fingerprint="${tx.fingerprint}"]`).click()
    await detail(page).getByRole('button', { name: t('transactions.actions.merchant') }).click()
    await expect(detail(page)).toHaveCount(0)
    await expect.poll(() => new URL(page.url()).searchParams.get('q')).toBe(tx.merchant)
    await expect(page).not.toHaveURL(/tx=/)
    const row = page
      .getByRole('region', { name: LIST })
      .locator(`[data-fingerprint="${tx.fingerprint}"]`)
    await expect(row).toBeInViewport({ ratio: 1 })
    await expect(row).toHaveAttribute('aria-pressed', 'true')
  })
})

test('a shared expense: «Open» shows its group summary in a sheet, and «Share» on another goes to «I paid it»', async ({
  page,
}) => {
  // The only test here that writes: it shares an expense through the API and undoes it at the end.
  const mark = await logMark(page.request)
  const [expense, other] = (await monthItems(page)).filter((tx) => tx.kind === 'expense' && tx.can_share)
  const group = await createGroup(page.request, 'Grupo del teléfono', [{ name: 'Ana Ficticia' }]) // spanish-data
  await addEntry(page.request, group.id, {
    fingerprint: expense.fingerprint,
    split: 'equal',
    people: group.members.map((m) => m.id),
  })
  try {
    await page.goto(`/transactions?month=${MONTH}`)
    await page.locator(`[data-fingerprint="${expense.fingerprint}"]`).click()
    await page
      .getByRole('region', { name: t('transactions.links.label') })
      .getByRole('button', {
        name: t('transactions.links.openLabel', { what: t('shared.tx.title') }),
      })
      .click()
    const summary = sheet(page, t('transactions.actions.share'))
    await expect(summary.getByTestId('tx-shared')).toBeVisible()
    await expect(summary.getByRole('link', { name: t('shared.tx.openGroup') })).toBeVisible()
    await noSidewaysScroll(page, 'shared sheet')
    await page.keyboard.press('Escape')
    await expect(summary).toHaveCount(0)

    // Another expense: «Share» opens «I paid it» with it, ready to pick the group.
    await page.getByRole('button', { name: t('transactions.detail.back') }).click()
    await page.locator(`[data-fingerprint="${other.fingerprint}"]`).click()
    await page
      .getByRole('group', { name: t('transactions.actions.label') })
      .getByRole('button', { name: t('transactions.actions.share') })
      .click()
    const add = sheet(page, t('shared.add.mine'))
    await expect(add).toContainText(other.merchant)
    await noSidewaysScroll(page, 'add expense sheet')
    await page.keyboard.press('Escape')
    await expect(add).toHaveCount(0)
  } finally {
    await undoSince(page.request, mark)
  }
})

test.describe('touch', () => {
  async function touch(page: Page) {
    const cdp = await page.context().newCDPSession(page)
    return (type: 'touchStart' | 'touchMove' | 'touchEnd', x = 0, y = 0) =>
      cdp.send('Input.dispatchTouchEvent', {
        type,
        touchPoints: type === 'touchEnd' ? [] : [{ x, y }],
      })
  }

  test('holding a finger on a row selects it; dragging it does not', async ({ page }) => {
    await page.goto(`/transactions?month=${MONTH}`)
    const list = page.getByRole('region', { name: LIST })
    const row = list.locator('[data-fingerprint]').nth(1)
    const box = (await row.boundingBox())!
    const x = box.x + box.width / 2
    const y = box.y + box.height / 2
    const send = await touch(page)
    const actions = page.getByRole('region', { name: t('transactions.selection.region') })

    // A drag (a scroll) is not a long-press, however long it lasts.
    await send('touchStart', x, y)
    await send('touchMove', x, y - 40)
    // Longer than the long-press: nothing may happen meanwhile.
    await page.waitForTimeout(800)
    await send('touchEnd')
    await expect(actions).toHaveCount(0)

    const fingerprint = await row.getAttribute('data-fingerprint')
    const again = (await list.locator(`[data-fingerprint="${fingerprint}"]`).boundingBox())!
    await send('touchStart', again.x + again.width / 2, again.y + again.height / 2)
    await expect(actions).toBeVisible()
    await send('touchEnd')
    await expect(
      list.locator(`[data-fingerprint="${fingerprint}"] input[type="checkbox"]`),
    ).toBeChecked()
    await expect(page.locator('[data-mobile-detail]')).toHaveCount(0)
    await page.keyboard.press('Escape')
  })
})

test('the month picker covers the bottom bar too', async ({ page }) => {
  await page.goto(`/?month=${MONTH}`)
  await page.getByRole('heading', { level: 1 }).getByRole('button').click()
  await expect(page.getByRole('dialog', { name: t('months.pick') })).toBeVisible()
  const barBox = (await bar(page).boundingBox())!
  const covered = await page.evaluate(
    ({ x, y }) => !document.elementFromPoint(x, y)?.closest('nav[data-bottom-bar]'),
    { x: barBox.x + barBox.width / 2, y: barBox.y + barBox.height / 2 },
  )
  expect(covered).toBe(true)
  await page.keyboard.press('Escape')
})

test.describe('summary', () => {
  test('month, what you kept, indicators, To review, then closed sections', async ({ page }) => {
    // A new browser context: no section remembered yet.
    await page.goto(`/?month=${MONTH}`)
    const kept = page.getByRole('region', { name: t('summary.mobile.kept') })
    const indicators = page.getByRole('region', { name: t('summary.mobile.indicators') })
    const review = page.getByRole('region', { name: literal(t('summary.review.title')) })
    await expect(kept).toBeVisible()
    await expect(kept).toContainText(t('summary.mobile.in'))
    await expect(kept).toContainText(t('summary.mobile.out'))
    const order = await Promise.all(
      [page.getByRole('heading', { level: 1 }), kept, indicators, review].map(
        async (locator) => (await locator.boundingBox())!.y,
      ),
    )
    expect([...order].sort((a, b) => a - b)).toEqual(order)

    // The strip scrolls sideways inside itself; the page does not.
    const strip = page.getByTestId('indicators')
    const sizes = await strip.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }))
    expect(sizes.scroll).toBeGreaterThan(sizes.client)
    await noSidewaysScroll(page, 'summary')

    // Sections start closed and remember being opened.
    const reading = page.getByRole('button', { name: t('summary.mobile.section.reading') })
    const details = page.getByRole('button', { name: t('summary.mobile.section.details') })
    await expect(reading).toHaveAttribute('aria-expanded', 'false')
    await expect(details).toHaveAttribute('aria-expanded', 'false')
    await expect(page.getByRole('region', { name: t('summary.kpi.sectionLabel'), exact: true })).toHaveCount(0)
    await details.click()
    await expect(page.getByRole('region', { name: t('summary.kpi.sectionLabel'), exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('button', { name: t('summary.mobile.section.details') })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    await expect(reading).toHaveAttribute('aria-expanded', 'false')
    await noSidewaysScroll(page, 'summary with details open')
    await page.getByRole('button', { name: t('summary.mobile.section.details') }).click()
  })
})

test('investments: legible rows and the detail in a sheet', async ({ page }) => {
  await page.goto('/investments?status=all')
  const list = page.getByRole('list', { name: t('investments.listLabel') })
  const first = list.getByRole('button').first()
  await expect(first).toBeVisible()
  await first.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('link', { name: /./ }).first()).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await noSidewaysScroll(page, 'investments')
})

test('investments: coming back from the investment screen shows the row without reopening it', async ({
  page,
}) => {
  await page.goto('/investments?status=all')
  const list = page.getByRole('list', { name: t('investments.listLabel') })
  const first = list.getByRole('button').first()
  await first.click()
  await page.getByRole('dialog').getByRole('link').first().click()
  await expect(page).toHaveURL(/\/transactions\//)
  await page.getByRole('link', { name: t('links.page.back') }).click()
  await expect(page).toHaveURL(/\/investments\?/)
  await expect(first).toBeFocused()
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('shared: no sideways scroll and 44 px targets', async ({ page }) => {
  await page.goto('/shared')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await noSidewaysScroll(page, 'shared')
  for (const target of await page.getByRole('main').locator('button:visible, a:visible').all()) {
    const box = (await target.boundingBox())!
    expect(box.height, await target.evaluate((el) => el.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44)
  }
})

for (const route of [
  '/',
  `/?month=${MONTH}`,
  `/transactions?month=${MONTH}`,
  '/shared',
  '/investments',
  '/budget',
  '/pending',
  '/recurring',
  '/reports',
  '/accounts',
  '/categories',
  '/log',
]) {
  test(`${route}: no sideways scrolling and nothing hidden under the bottom bar`, async ({
    page,
  }) => {
    await page.goto(route)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    await noSidewaysScroll(page, route)
    const main = (await page.getByRole('main').boundingBox())!
    const barTop = (await bar(page).boundingBox())!.y
    // Scrolled to the end (while the page may still be loading), the last thing in the content
    // ends above the bar.
    await expect
      .poll(
        () =>
          page.getByRole('main').evaluate((el) => {
            window.scrollTo(0, document.documentElement.scrollHeight)
            const last = el.lastElementChild as HTMLElement | null
            return last ? last.getBoundingClientRect().bottom : el.getBoundingClientRect().top
          }),
        { message: route },
      )
      .toBeLessThanOrEqual(barTop + 1)
    expect(main.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  })
}
