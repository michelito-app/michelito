import { expect, test, type Page } from '@playwright/test'
import { LOCALE, message } from '../src/i18n'
import { escapeRegExp, literal, t } from './text'

// Made-up data from tests/e2e_server.py: the gift for Luis (RD$ 4,000, «I paid it for someone
// else», pending), CLOTHES (RD$ 4,350 split in two, settled with RD$ 2,175 in cash) and
// the bookshop with Rosa (written off). board.spec.ts runs earlier on the same database and may
// leave other groups: these rows are looked up by name.
const CLOTHES = 'Ropa de Marta' // spanish-data: a group title in the e2e data

// Where a value goes inside a catalog message, to match it with a pattern.
const HOLE = '\u0000'

/** The catalog `text` (with HOLE where a value goes) as an anchored RegExp, `source` in the hole. */
function withHole(text: string, source: string): RegExp {
  return new RegExp(`^${text.split(HOLE).map(escapeRegExp).join(source)}$`)
}

/** "2025-12-20" → "<day> <first three letters of the month>", as the app writes it (Intl). */
function shortDay(iso: string): string {
  const month = new Intl.DateTimeFormat(LOCALE, { month: 'long', timeZone: 'UTC' }).format(
    new Date(`${iso}T00:00:00Z`),
  )
  return `${Number(iso.slice(8, 10))} ${month.slice(0, 3)}`
}

/** The group's meta line: with whom (when not the title), expense count and date. */
function meta(parts: { who?: string; expenses: number; day: string }): string {
  const date = `${shortDay(parts.day)} ${parts.day.slice(0, 4)}`
  return [parts.who, t('links.expenseCount', { count: parts.expenses }), date]
    .filter((part) => part !== undefined)
    .join(' · ')
}

function groups(page: Page) {
  return page.getByRole('list', { name: t('shared.listLabel') })
}

function row(page: Page, title: RegExp) {
  return groups(page).getByRole('button', { name: title })
}

const chips = (page: Page) => page.getByRole('group', { name: t('shared.chipsLabel') })
const chip = (label: string) => ({ name: literal(label, { start: true }) })
const newGroup = (page: Page) => page.getByRole('button', { name: t('shared.newGroup.open') })
const newGroupPanel = (page: Page) =>
  page.getByRole('region', { name: t('shared.newGroup.title') })
const shareButton = (merchant: string) => ({
  name: literal(t('shared.newGroup.shareLabel', { merchant }), { start: true }),
})

test('the menu opens Shared with a pending group, a settled one and a written-off one', async ({
  page,
}) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: t('shell.nav.label') })
    .getByRole('link', { name: t('shell.nav.shared') })
    .click()
  await expect(page).toHaveURL(/\/shared$/)
  await expect(page.getByRole('heading', { level: 1, name: t('shared.title') })).toBeVisible()

  const gift = row(page, /^Luis/)
  await expect(gift).toContainText(t('shared.status.owed', { amount: 'RD$ 4,000' }))
  await expect(gift).toContainText(meta({ expenses: 1, day: '2025-12-20' }))
  await expect(gift).toContainText(
    t('shared.moneyLine', { paid: 'RD$ 4,000', back: t('shared.moneyLine.nothingBack') }),
  )
  const clothes = row(page, literal(CLOTHES, { start: true }))
  await expect(clothes).toContainText(t('shared.status.settled'))
  await expect(clothes).toContainText(meta({ who: 'Marta', expenses: 1, day: '2025-12-18' }))
  await expect(clothes).toContainText(
    t('shared.moneyLine', {
      paid: 'RD$ 4,350',
      back: t('shared.moneyLine.paidBack', { amount: 'RD$ 2,175' }),
    }),
  )
  await expect(row(page, /^Rosa/)).toContainText(t('shared.status.lost'))

  const approx = withHole(t('shared.approx', { amount: HOLE }), 'RD\\$ [\\d,]+')
  await expect(page.getByTestId('shared-owed')).toHaveText(approx)
  await expect(page.getByTestId('shared-year')).toHaveText(approx)
  const open = message('shared.figure.openCount')
  const openCount = [open.one, open.other]
    .map((form) => form.split('{count}').map(escapeRegExp).join('\\d+'))
    .join('|')
  await expect(page.getByTestId('shared-open')).toHaveText(new RegExp(`^(?:${openCount})$`))
  // Most recent first: Marta's cash (10 Jan) comes before the gift (20 Dec).
  const titles = await groups(page).getByRole('button').allTextContents()
  const order = (prefix: string) => titles.findIndex((text) => text.startsWith(prefix))
  expect(order(CLOTHES)).toBeLessThan(order('Luis'))
})

test('the chips and the search box filter, and go in the URL', async ({ page }) => {
  await page.goto('/shared')
  await expect(chips(page).getByRole('button', chip(t('shared.chip.all')))).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  await chips(page).getByRole('button', chip(t('shared.chip.settled'))).click()
  await expect(page).toHaveURL(/status=settled/)
  await expect(row(page, literal(CLOTHES, { start: true }))).toBeVisible()
  await expect(row(page, /^Luis/)).toHaveCount(0)

  await chips(page).getByRole('button', chip(t('shared.chip.all'))).click()
  await expect(page).not.toHaveURL(/status=/)
  const search = page.getByRole('searchbox', { name: t('shared.searchLabel') })
  await search.fill('rosa')
  await expect(page).toHaveURL(/q=rosa/)
  await expect(row(page, /^Rosa/)).toBeVisible()
  await expect(row(page, /^Luis/)).toHaveCount(0)

  await search.fill('4,350') // an amount, as in the pickers
  await expect(row(page, literal(CLOTHES, { start: true }))).toBeVisible()
  await expect(row(page, /^Rosa/)).toHaveCount(0)

  await search.fill('regalos') // spanish-data: the merchant of an expense
  await expect(row(page, /^Luis/)).toBeVisible()
  await chips(page).getByRole('button', chip(t('shared.chip.lost'))).click()
  await expect(
    page.getByText(t('shared.noneMatching', { none: t('shared.none.lost'), query: 'regalos' })),
  ).toBeVisible()
})

test('a row expands; «Manage…» and «Back» return with it expanded', async ({ page }) => {
  await page.goto('/shared?status=pending')
  const gift = row(page, /^Luis/)
  await expect(gift).toHaveAttribute('aria-expanded', 'false')
  await gift.click()
  await expect(gift).toHaveAttribute('aria-expanded', 'true')
  await expect(page).toHaveURL(/group=\d+/)
  const expenses = page.getByRole('region', { name: t('shared.row.expensesLabel', { title: 'Luis' }) })
  await expect(expenses).toContainText(
    t('links.linkedLabel', { merchant: 'TIENDA REGALOS', day: shortDay('2025-12-20') }),
  )
  await expect(expenses).toContainText(t('links.split.forOther'))
  await expect(expenses).toContainText(t('shared.expensePending', { amount: 'RD$ 4,000' }))
  await expect(
    page.getByRole('region', { name: t('shared.row.refundsLabel', { title: 'Luis' }) }),
  ).toContainText(t('shared.row.noRefunds'))
  const back = page.url()

  await page.getByRole('link', { name: t('shared.row.manageLabel', { title: 'Luis' }) }).click()
  await expect(page).toHaveURL(/\/transactions\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/TIENDA REGALOS/)

  await page.getByRole('link', { name: t('links.page.back') }).click()
  await expect(page).toHaveURL(back)
  const pending = chips(page).getByRole('button', chip(t('shared.chip.pending')))
  await expect(pending).toHaveAttribute('aria-pressed', 'true')
  await expect(row(page, /^Luis/)).toHaveAttribute('aria-expanded', 'true')
  await expect(row(page, /^Luis/)).toBeFocused() // its row gets focus on the way back
  await expect(
    page.getByRole('region', { name: t('shared.row.expensesLabel', { title: 'Luis' }) }),
  ).toBeVisible()
})

test('the expanded group stays in the list even when it no longer matches the chip', async ({
  page,
}) => {
  await page.goto('/shared')
  await row(page, /^Luis/).click()
  await expect(page).toHaveURL(/group=\d+/)
  const group = new URL(page.url()).searchParams.get('group')

  // As when coming back from its screen after changing the chip: Luis is pending, not settled.
  await page.goto(`/shared?status=settled&group=${group}`)
  await expect(row(page, literal(CLOTHES, { start: true }))).toBeVisible()
  const gift = row(page, /^Luis/)
  await expect(gift).toHaveAttribute('aria-expanded', 'true')
  // With its current status.
  await expect(gift).toContainText(t('shared.status.owed', { amount: 'RD$ 4,000' }))
  await expect(gift).toBeFocused()

  // Collapsing and expanding it does not drop it; changing the search does.
  await gift.click()
  await expect(gift).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('searchbox', { name: t('shared.searchLabel') }).fill('ropa') // spanish-data
  await expect(row(page, /^Luis/)).toHaveCount(0)
  await expect(row(page, literal(CLOTHES, { start: true }))).toBeVisible()
})

test('with accounts that have no groups it says so and lets you create one', async ({ page }) => {
  await page.goto(`/shared?accounts=${encodeURIComponent('bhd:savings:999-1')}`)
  await expect(page.getByText(t('shared.emptyChosen'))).toBeVisible()
  await expect(newGroup(page)).toBeVisible()
})

test('«New group…» leads to the expense with «Share» open', async ({ page }) => {
  await page.goto('/shared')
  await newGroup(page).click()
  const panel = newGroupPanel(page)
  const list = panel.getByRole('list', { name: t('shared.newGroup.listLabel') })
  await expect(list.getByRole('listitem').first()).toBeVisible()
  // What is already shared and the withdrawals are not in the whole list (not only what shows).
  const search = panel.getByRole('searchbox')
  for (const text of ['regalos', 'retiro', 'libreria']) { // spanish-data: merchant words
    await search.fill(text)
    await expect(panel.getByText(t('transactions.picker.noMatch', { query: text }))).toBeVisible()
  }

  await search.fill('gasolinera') // spanish-data: a merchant word
  await panel.getByRole('button', shareButton('GASOLINERA')).click()
  await expect(page).toHaveURL(/\/transactions\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/GASOLINERA/)
  await expect(page.getByRole('heading', { level: 2, name: t('links.share.title') })).toBeVisible()
  await expect(page.getByRole('button', { name: t('links.share.mark') })).toBeVisible()

  await page.getByRole('link', { name: t('links.page.back') }).click()
  await expect(page).toHaveURL(/\/shared$/)
})

test('«New group…» suggests the big dinner on top and leaves the tax under «See more»', async ({
  page,
}) => {
  await page.goto('/shared')
  await newGroup(page).click()
  const panel = newGroupPanel(page)
  await expect(panel).toContainText(t('shared.newGroup.help'))
  const list = panel.getByRole('list', { name: t('shared.newGroup.listLabel') })
  const tax = panel.getByRole('button', shareButton('IMPUESTO'))
  // ASADOR FICTICIO CUMPLEANOS (RD$ 5,200, 9 Feb): the most recent suggestion, the first one.
  await expect(list.getByRole('listitem').first()).toContainText('ASADOR FICTICIO')
  await expect(tax).toHaveCount(0) // the RD$ 3 tax is not suggested

  await panel
    .getByRole('button', { name: withHole(t('transactions.picker.seeMore', { count: HOLE }), '\\d+') })
    .click()
  await expect(tax).toBeVisible()
  await panel.getByRole('button', { name: t('transactions.picker.seeLess') }).click()
  await expect(tax).toHaveCount(0)

  // The search box searches the whole list, also what is not suggested.
  await panel.getByRole('searchbox').fill('impuesto') // spanish-data: a merchant word
  await expect(tax).toBeVisible()
})

test('«New group…» with the keyboard: focus goes to the search box and back to the button', async ({
  page,
}) => {
  await page.goto('/shared')
  const trigger = newGroup(page)
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await trigger.focus()
  await page.keyboard.press('Enter')

  const panel = newGroupPanel(page)
  await expect(trigger).toHaveAttribute('aria-expanded', 'true')
  await expect(trigger).toHaveAttribute('aria-controls', (await panel.getAttribute('id')) ?? '')
  await expect(panel.getByRole('searchbox')).toBeFocused()
  await page.keyboard.type('cine') // spanish-data: a merchant word
  await expect(panel.getByRole('button', shareButton('CINE'))).toBeVisible()

  await panel.getByRole('button', { name: t('shared.newGroup.close') }).focus()
  await page.keyboard.press('Enter')
  await expect(panel).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
})

test('at 390 px there is no horizontal scroll and touch targets are 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/shared')
  await row(page, literal(CLOTHES, { start: true })).click()
  await expect(
    page.getByRole('region', { name: t('shared.row.refundsLabel', { title: CLOTHES }) }),
  ).toContainText([t('shared.refund.manual'), 'Marta', t('shared.refund.cash')].join(' · '))
  await newGroup(page).click()
  await expect(page.getByRole('list', { name: t('shared.newGroup.listLabel') })).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const targets = page
    .getByRole('main')
    .locator('button:visible, a:visible, input:visible')
  for (const target of await targets.all()) {
    const box = await target.boundingBox()
    expect(box?.height ?? 0, await target.evaluate((el) => el.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44)
  }
})
