import { expect, test, type Page } from '@playwright/test'
import { chooseFilter } from './phone'
import { literal, t } from './text'

// The `--household` server of tests/e2e_server.py (made-up data): the P2P account with
// three credits from different third parties for selling crypto (all with "P2P" in the
// description, RD$ 40,500 in January) that fall in the "other income" category. Each test
// undoes in the Log what it did. Log lines are written by the backend catalog: data here.
const MONTH = '2026-01'
const CRYPTO = 'Cripto' // spanish-data: seeded category
const OTHER_INCOME = 'Otros ingresos' // spanish-data: seeded category
const LINE = `3 transacciones · ${OTHER_INCOME} → ${CRYPTO}` // spanish-data: backend log line
const REASON = 'Venta de USDT por P2P' // spanish-data: typed reason
const LIST = t('transactions.list.label')
const BAR = t('transactions.selection.region')
const SELECT = t('transactions.select')
const SELECT_ALL = literal(t('transactions.selection.selectAll', { count: '' }).replace(' ()', ''), {
  start: true,
})

/** "N seleccionadas · <money>" as the selection bar shows it. */
function counter(count: number, money?: string): string {
  const text = t('common.selection.count', { count })
  return money === undefined ? text : `${text} · ${money}`
}

/** The start of a row checkbox's name: "Seleccionar <day> <merchant>". */
function pick(day: string, merchant: string): RegExp {
  return literal(t('transactions.list.pick', { day, merchant, amount: '' }).trimEnd(), {
    start: true,
  })
}

const JAN_8 = '8 ene' // spanish-ui: short day built with Intl
const JAN_16 = '16 ene' // spanish-ui: short day built with Intl
const JAN_27 = '27 ene' // spanish-ui: short day built with Intl

async function filterCrypto(page: Page) {
  await page.goto(`/transactions?month=${MONTH}`)
  const search = page.getByRole('search')
  await chooseFilter(page, t('transactions.filters.kind'), t('transactions.kind.income'))
  await chooseFilter(page, t('transactions.filters.category'), OTHER_INCOME)
  await search.getByRole('searchbox').fill('P2P')
  await expect(page).toHaveURL(/q=P2P/)
  const list = page.getByRole('region', { name: LIST })
  await expect(list.getByRole('button')).toHaveCount(3)
  return list
}

async function undoBatch(page: Page) {
  await page.goto('/log')
  await page.getByRole('searchbox', { name: t('log.filter.search') }).fill(CRYPTO)
  await page.getByRole('button', { name: t('log.row.undoNamed', { name: LINE }), exact: true }).click()
  // The same row turns undone and offers «Rehacer» (no new «Deshecho: …» row).
  await expect(
    page.getByRole('button', { name: t('log.row.redoNamed', { name: LINE }), exact: true }),
  ).toBeVisible()
}

test('filtering, selecting several, moving them to crypto with a reason and undoing in the Log', async ({
  page,
}) => {
  const list = await filterCrypto(page)
  await page.getByRole('button', { name: SELECT, exact: true }).click()
  const bar = page.getByRole('region', { name: BAR })
  await expect(bar).toContainText(counter(0, 'RD$ 0'))
  // Focus goes to the first checkbox; each one says the day.
  await expect(list.getByRole('checkbox').first()).toBeFocused()

  await list.getByRole('checkbox', { name: pick(JAN_8, 'MB DESDE') }).check()
  await list.getByRole('checkbox', { name: pick(JAN_16, 'TRANSFERENCIA RECIBIDA') }).check()
  await expect(bar).toContainText(counter(2, 'RD$ 20,500'))
  await bar
    .getByRole('button', { name: t('transactions.selection.selectAll', { count: 3 }) })
    .click()
  await expect(bar).toContainText(counter(3, 'RD$ 40,500'))
  await expect(list.getByRole('checkbox', { checked: true })).toHaveCount(3)

  await bar
    .getByRole('combobox', { name: t('transactions.selection.newCategory'), exact: true })
    .selectOption(CRYPTO)
  const reason = bar.getByRole('textbox', { name: t('transactions.selection.reason'), exact: true })
  await reason.fill(REASON)
  await reason.press('Escape') // Escape in a field of the bar does not leave the mode
  await expect(bar).toContainText(counter(3))
  await bar.getByRole('button', { name: t('transactions.selection.change'), exact: true }).click()
  const applied = t('common.selection.applied', { count: 3, category: CRYPTO })
  const notice = page.getByRole('status').filter({ hasText: applied })
  await expect(notice).toContainText(applied)
  await expect(notice).toBeFocused()
  await expect(notice.getByRole('link', { name: t('transactions.selection.seeLog') })).toBeVisible()
  await expect(bar).toHaveCount(0)
  // They are no longer other income: with the same filter the list is empty.
  await expect(page.getByRole('main')).toContainText(t('transactions.empty'))

  // Crypto <-> fiat is neutral, like a currency exchange: Reports no longer count it as income.
  await page.goto(`/reports?month=${MONTH}`)
  await expect(page.getByTestId('income-lines')).toBeVisible()
  await expect(page.getByTestId('income-lines')).not.toContainText(CRYPTO)

  await page.getByRole('link', { name: t('shell.nav.log') }).first().click()
  await page.getByRole('searchbox', { name: t('log.filter.search') }).fill(CRYPTO)
  await expect(page.getByRole('main')).toContainText(LINE)
  await expect(page.getByRole('main')).toContainText(t('log.reason.value', { reason: REASON }))
  await undoBatch(page)

  const back = await filterCrypto(page)
  await expect(back.getByRole('button', { name: /P2P/ })).toHaveCount(3)
})

test('at 390 px the bar stays at the bottom without covering the list or overflowing; Escape leaves', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const list = await filterCrypto(page)
  await page.getByRole('button', { name: SELECT, exact: true }).click()
  const bar = page.getByRole('region', { name: BAR })
  await bar
    .getByRole('button', { name: t('transactions.selection.selectAll', { count: 3 }) })
    .click()
  await expect(bar).toContainText(counter(3, 'RD$ 40,500'))

  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  expect(widths.scroll).toBeLessThanOrEqual(widths.client)
  // At the bottom: on a phone, right on top of the bottom navigation bar.
  const box = await bar.boundingBox()
  const navigation = await page.locator('nav[data-bottom-bar]').boundingBox()
  expect(box && box.y + box.height).toBeCloseTo(navigation ? navigation.y : 844, 0)
  // At the end of the page the last row stays above the bar.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  const last = list.getByRole('checkbox').last()
  const row = await last.boundingBox()
  const barTop = (await bar.boundingBox())!.y
  expect(row!.y + row!.height).toBeLessThanOrEqual(barTop)
  const checkbox = await list.locator('label').first().boundingBox()
  expect(checkbox!.height).toBeGreaterThanOrEqual(44)

  await page.keyboard.press('Escape')
  await expect(bar).toHaveCount(0)
  await expect(list.getByRole('button')).toHaveCount(3)
})

test('with groups, "Select all visible" only checks the open groups', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}&kind=income&group=category`)
  const list = page.getByRole('region', { name: LIST })
  await page.getByRole('button', { name: SELECT, exact: true }).click()
  const bar = page.getByRole('region', { name: BAR })
  // All folded: no row shows, there is nothing to "select all".
  await expect(bar.getByRole('button', { name: SELECT_ALL })).toHaveCount(0)

  await list.getByRole('button', { name: /^Salario/ }).click() // spanish-data: seeded category
  await bar
    .getByRole('button', { name: t('transactions.selection.selectAll', { count: 1 }), exact: true })
    .click()
  await expect(bar).toContainText(counter(1, 'RD$ 85,000'))
  await expect(bar.getByRole('button', { name: SELECT_ALL })).toHaveCount(0)
  await list.getByRole('button', { name: literal(OTHER_INCOME, { start: true }) }).click()
  await expect(list.getByRole('checkbox', { checked: true })).toHaveCount(1)
  await page.getByRole('button', { name: t('transactions.cancel'), exact: true }).click()
  await expect(bar).toHaveCount(0)
})

test('chosen rows that leave the filter are released and do not come back', async ({ page }) => {
  const list = await filterCrypto(page)
  await page.getByRole('button', { name: SELECT, exact: true }).click()
  const bar = page.getByRole('region', { name: BAR })
  await list.getByRole('checkbox', { name: pick(JAN_8, 'MB DESDE') }).check()
  await list.getByRole('checkbox', { name: pick(JAN_27, 'LBTR') }).check()
  await expect(bar).toContainText(counter(2))

  const search = page.getByRole('search').getByRole('searchbox')
  await search.fill('MB DESDE')
  await expect(list.getByRole('checkbox')).toHaveCount(1)
  await expect(bar).toContainText(counter(1, 'RD$ 12,000'))
  await search.fill('P2P')
  await expect(list.getByRole('checkbox')).toHaveCount(3)
  await expect(bar).toContainText(counter(1, 'RD$ 12,000'))
  await expect(list.getByRole('checkbox', { name: pick(JAN_27, 'LBTR') })).not.toBeChecked()
})

test('on desktop the bar starts where the content starts (it does not cover the menu)', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1400, height: 900 })
  await filterCrypto(page)
  await page.getByRole('button', { name: SELECT, exact: true }).click()
  const bar = page.getByRole('region', { name: BAR })
  const nav = await page.getByRole('navigation', { name: t('shell.nav.label') }).boundingBox()
  const main = await page.getByRole('main').boundingBox()
  await expect
    .poll(async () => (await bar.boundingBox())?.x)
    .toBeCloseTo(main!.x, 0)
  expect(main!.x).toBeGreaterThanOrEqual(nav!.x + nav!.width - 1)
})
