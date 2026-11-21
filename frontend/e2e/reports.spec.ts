import { expect, test } from '@playwright/test'
import { literal, t } from './text'

// Made-up data from tests/e2e_server.py: December 2025 complete; January and February in
// progress. This file runs after board.spec.ts on the same database: it does not depend on what
// was marked there (it only reads, or undoes what it marks).
// Row and month labels of the comparison come from the backend catalog (web.report.*, month
// labels), so they are data here.
const COMPARE = t('reports.compare.title')
const INSIGHTS = t('reports.insights.title')
const DECEMBER_LABEL = 'Diciembre 2025' // spanish-data: backend month label
const STREAMING = 'STREAMING FICTICIO'

test('reports: the menu leads to the table of months', async ({ page }) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: t('shell.nav.label') })
    .getByRole('link', { name: t('shell.nav.reports') })
    .click()
  await expect(page.getByRole('heading', { level: 1, name: t('reports.page.title') })).toBeVisible()
  const table = page.getByRole('region', { name: COMPARE })
  await expect(table.getByRole('columnheader')).toContainText([
    t('reports.compare.row'),
    'Diciembre 25', // spanish-data: backend month label
    /Enero 26/, // spanish-data: backend month label
    /Febrero 26/, // spanish-data: backend month label
  ])
  const rows = table.getByRole('rowheader')
  await expect(rows.nth(0)).toHaveText('Ingresos') // spanish-data: web.report.income
  await expect(rows.nth(1)).toHaveText('Gastos') // spanish-data: web.report.expenses
  await expect(rows.nth(2)).toHaveText('Transferencias a terceros') // spanish-data: web.report.third_party
  await expect(rows.nth(3)).toHaveText('Te quedó') // spanish-data: web.report.net
  await expect(table.getByRole('row', { name: /^Gastos/ })).toContainText('19,883') // spanish-data
})

test('reports: a cell opens Transactions with the month, the category and the accounts', async ({
  page,
}) => {
  await page.goto('/reports?accounts=demo%3Acredit_card')
  const table = page.getByRole('region', { name: COMPARE })
  const cell = t('reports.compare.cellLabel', {
    row: 'Viajes', // spanish-data: seeded category
    month: 'Febrero 2026', // spanish-data: backend month label
    amount: '45,000',
    title: '',
  })
  await table.getByRole('link', { name: literal(cell.replace(/\. $/, ''), { start: true }) }).click()
  await expect(page).toHaveURL(/\/transactions\?month=2026-02&category=Viajes&accounts=demo%3Acredit_card/)
  await expect(page.getByRole('heading', { level: 1, name: t('transactions.title') })).toBeVisible()
})

test('reports: the range is chosen with "From" and "To"', async ({ page }) => {
  await page.goto('/reports')
  const table = page.getByRole('region', { name: COMPARE })
  await table.getByLabel(t('reports.compare.from')).selectOption('2026-01')
  await expect(page).toHaveURL(/from=2026-01/)
  await expect(table.getByRole('columnheader', { name: /Diciembre/ })).toHaveCount(0) // spanish-data
  await expect(table.getByRole('columnheader', { name: /Enero 26/ })).toBeVisible() // spanish-data
})

test('reports: the "To review" history filters by kind and allows reviewing again', async ({
  page,
}) => {
  await page.goto('/reports')
  const history = page.getByRole('region', { name: t('reports.history.title') })
  await expect(history).toContainText(STREAMING)
  const largeTransfer = history.getByRole('button', {
    name: t('review.kind.largeThirdParty'),
    exact: true,
  })
  await largeTransfer.click()
  await expect(largeTransfer).toHaveAttribute('aria-pressed', 'true')
  await expect(history).not.toContainText(STREAMING)

  // Only price rises; the streaming item may be reviewed or not: it is changed and undone.
  await history.getByRole('button', { name: t('review.kind.priceUp'), exact: true }).click()
  const undo = history.getByRole('button', {
    name: t('review.row.reviewAgainLabel', { merchant: STREAMING }),
  })
  const done = history.getByRole('button', { name: t('review.reviewedLabel', { merchant: STREAMING }) })
  await expect(undo.or(done)).toBeVisible()
  const wasReviewed = await undo.isVisible()
  await (wasReviewed ? undo : done).click()
  await expect(wasReviewed ? done : undo).toBeVisible()
  await (wasReviewed ? done : undo).click()
  await expect(wasReviewed ? undo : done).toBeVisible()
})

test('reports: at 390 px the table scrolls inside its box, not the page', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/reports')
  const scroller = page
    .getByRole('region', { name: COMPARE })
    .getByLabel(literal(t('reports.compare.tableLabel').split(' (')[0]))
  await expect(scroller).toBeVisible()
  const pageWidth = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(pageWidth).toBeLessThanOrEqual(390)
  const overflow = await scroller.evaluate((el) => el.scrollWidth > el.clientWidth)
  expect(overflow).toBe(true)
})

test.describe('saved insights', () => {
  test.describe.configure({ mode: 'serial' })
  const DECEMBER = '2025-12'
  const TEXT = 'Diciembre: la ferretería explica casi todo el gasto.' // spanish-data
  const CORRECTED = 'Diciembre corregido.' // spanish-data

  test('reports: a month without insight offers to copy the command', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto('/reports')
    const section = page.getByRole('region', { name: INSIGHTS, exact: true })
    await expect(section).toContainText('michelito analysis 2025-12')
    const copy = section.getByRole('button', {
      name: t('reports.insights.copyCommandLabel', { label: DECEMBER_LABEL }),
    })
    await copy.click()
    await expect(copy).toHaveText(t('summary.insight.copied'))
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('michelito analysis 2025-12')
  })

  test('summary: the saved insight shows in the Insight tab of "Month reading"', async ({
    page,
    request,
  }) => {
    // Like `michelito insight save`: the API saves it with the fingerprint of today's data.
    const saved = await request.put(`/api/insights/${DECEMBER}`, {
      headers: { 'X-Michelito': '1' },
      data: { text: TEXT },
    })
    expect(saved.ok()).toBe(true)
    await page.goto(`/reports?month=${DECEMBER}`)
    const card = page.getByRole('region', { name: t('summary.reading.title') })
    const tab = card.getByRole('tab', { name: t('summary.reading.tab.insight') })
    await expect(tab).toHaveAttribute('aria-selected', 'true')
    await expect(card.getByRole('tabpanel')).toContainText(TEXT)
    // Not even the start of the stale note.
    await expect(card).not.toContainText(t('reports.insight.stale').split(' ').slice(0, 3).join(' '))
    await page.goto('/reports?month=2026-01')
    await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible() // spanish-ui: month title built with Intl
    await expect(page.getByRole('tab', { name: t('summary.reading.tab.insight') })).toHaveCount(0)
  })

  test('reports: it is edited and deleted', async ({ page }) => {
    await page.goto('/reports')
    const section = page.getByRole('region', { name: INSIGHTS, exact: true })
    const saved = section.getByRole('list', { name: t('reports.insights.savedLabel') })
    await expect(saved).toContainText(DECEMBER_LABEL)
    await expect(section).not.toContainText('michelito analysis 2025-12')
    await saved
      .getByRole('button', { name: t('reports.insights.editAction', { label: DECEMBER_LABEL }) })
      .click()
    await saved.getByLabel(t('reports.insights.editLabel', { label: DECEMBER_LABEL })).fill(CORRECTED)
    await saved.getByRole('button', { name: t('common.save') }).click()
    await expect(saved).toContainText(CORRECTED)

    await saved
      .getByRole('button', { name: t('reports.insights.deleteAction', { label: DECEMBER_LABEL }) })
      .click()
    await saved.getByRole('button', { name: t('reports.insights.yesDelete') }).click()
    await expect(section).toContainText('michelito analysis 2025-12')
    await expect(section.getByRole('list', { name: t('reports.insights.savedLabel') })).toHaveCount(0)
  })
})
