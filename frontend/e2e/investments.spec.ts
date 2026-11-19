import { expect, test, type Page } from '@playwright/test'
import { LOCALE } from '../src/i18n'
import { escapeRegExp, literal, t } from './text'

// Made-up data from tests/e2e_server.py, December 2025, on the savings account: transfers to
// Pedro (RD$ 300,000 on the 2nd, RD$ 100,000 on the 15th and a small one of RD$ 1,500 on the
// 18th) and what came back (RD$ 9,000 on the 22nd and RD$ 60,000 on the 29th); and the loan to
// Ana (ANA_LOAN: RD$ 50,000 that came back with RD$ 2,000 extra), already closed. The tests run
// in order: the first one marks the investment.

const DECEMBER = '2025-12'
const PEDRO = 'Negocio de Pedro' // spanish-data: the investment name typed by the test
const ANA_LOAN = 'Préstamo a Ana' // spanish-data: an investment in the e2e data

// Where a value goes inside a catalog message, to match it with a pattern.
const HOLE = '\u0000'

/** The start of a catalog message, up to where its value goes. */
function startOf(text: string): string {
  return text.split(HOLE)[0]
}

/** "2025-12-02" → "<day> <first three letters of the month>", as the app writes it (Intl). */
function shortDay(iso: string): string {
  const month = new Intl.DateTimeFormat(LOCALE, { month: 'long', timeZone: 'UTC' }).format(
    new Date(`${iso}T00:00:00Z`),
  )
  return `${Number(iso.slice(8, 10))} ${month.slice(0, 3)}`
}

/** A figure of an investment: its label followed by the amount. */
const stat = (label: string, amount: string) => `${label}${amount}`

const investedNote = (amount: string) => t('investments.investedNote', { amount })

const mixed = (capital: string, returns: string) =>
  t('investments.entry.mixed', { capital, returns, extra: '' })

function list(page: Page) {
  return page.getByRole('list', { name: t('investments.listLabel') })
}

function row(page: Page, title: string) {
  return list(page).getByRole('button', { name: literal(title, { start: true }) })
}

async function openTransaction(page: Page, name: RegExp) {
  await page.goto(`/transactions?month=${DECEMBER}`)
  await page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .getByRole('button', { name })
    .click()
  return page.getByRole('complementary')
}

test.describe.configure({ mode: 'serial' })

test('a debit is marked as an investment: it does not reduce what you kept', async ({ page }) => {
  await page.goto(`/?month=${DECEMBER}`)
  const kpis = page.getByRole('region', { name: t('summary.kpi.sectionLabel') })
  await expect(kpis.getByTestId('invested-note')).toHaveText(investedNote('RD$ 50,000'))

  const detail = await openTransaction(page, /^MB A 0000000066.*RD\$ 300,000$/)
  const section = detail.getByRole('region', { name: t('links.summary.investmentTitle') })
  await expect(section).toContainText(t('links.summary.investmentOffer'))
  await section.getByRole('button', { name: t('links.action.isInvestment') }).click()

  await expect(page).toHaveURL(/\/transactions\/[^/?]+$/)
  await page.getByLabel(t('links.investment.withWhom')).fill('Pedro')
  await page.getByLabel(t('links.investment.name')).fill(PEDRO)
  await page.getByRole('button', { name: t('links.investment.mark') }).click()

  const panel = page.getByTestId('investment-panel')
  await expect(panel).toContainText(
    t('links.investment.heading', { status: t('investments.status.active') }),
  )
  await expect(panel).toContainText(PEDRO)
  await expect(panel.getByTestId('investment-line')).toContainText(
    stat(t('investments.stat.contributed'), 'RD$ 300,000'),
  )
  await expect(panel.getByTestId('investment-line')).toContainText(
    stat(t('investments.stat.pending'), 'RD$ 300,000'),
  )
  // The link decides its category.
  await expect(page.getByRole('main').locator('header')).toContainText('MB A 0000000066')

  await page.goto(`/?month=${DECEMBER}`)
  await expect(kpis.getByTestId('invested-note')).toHaveText(investedNote('RD$ 350,000'))
})

test('a return and a mixed repayment are linked', async ({ page }) => {
  const detail = await openTransaction(page, /^TRANSF PEDRO INVERSOR.*RD\$ 9,000$/)
  await detail
    .getByRole('region', { name: t('links.summary.investmentTitle') })
    .getByRole('button', { name: t('links.action.fromInvestment') })
    .click()

  await expect(page.getByText(t('links.investment.isReturnOf', { title: PEDRO }))).toBeVisible()
  // By its own accessible name: the label's would include the chosen option.
  await page
    .getByRole('combobox', { name: t('links.summary.investmentTitle'), exact: true })
    .selectOption({ label: `${PEDRO} · ${t('investments.status.active')}` })
  await page.getByRole('radio', { name: t('links.role.return'), exact: true }).check()
  await page.getByRole('button', { name: t('links.investment.link') }).click()

  const panel = page.getByTestId('investment-panel')
  await expect(panel.getByTestId('investment-line')).toContainText(
    stat(t('investments.stat.returns'), 'RD$ 9,000'),
  )
  await expect(
    panel.getByRole('list', { name: t('links.investment.creditsList') }),
  ).toContainText(t('links.role.return'))

  // The RD$ 60,000 one is mixed: RD$ 50,000 of capital and the rest, return.
  await panel.getByRole('button', { name: t('links.investment.addCredit') }).click()
  await panel
    .getByRole('button', {
      name: t('links.investment.addMerchant', { merchant: 'TRANSF PEDRO INVERSOR' }),
    })
    .click()
  await panel.getByRole('radio', { name: literal(t('links.role.mixed'), { start: true }) }).check()
  const capital = panel.getByLabel(t('links.role.capitalPart'))
  await capital.fill('60000')
  await panel.getByRole('button', { name: t('links.investment.addToInvestment') }).click()
  await expect(panel.getByRole('alert')).toContainText(t('investments.role.capitalTooBig'))
  await capital.fill('50,000')
  await panel.getByRole('button', { name: t('links.investment.addToInvestment') }).click()

  const line = panel.getByTestId('investment-line')
  await expect(line).toContainText(stat(t('investments.stat.returned'), 'RD$ 50,000'))
  await expect(line).toContainText(stat(t('investments.stat.returns'), 'RD$ 19,000'))
  await expect(line).toContainText(stat(t('investments.stat.pending'), 'RD$ 250,000'))
  await expect(panel).toContainText(mixed('RD$ 50,000', 'RD$ 10,000'))
})

test('«To review» proposes another contribution and confirming it is one tap', async ({ page }) => {
  await page.goto(`/?month=${DECEMBER}`)
  const card = page.getByRole('region', { name: literal(t('summary.review.title')) })
  await expect(card).toContainText(t('review.kind.possibleContribution'))
  // The reason comes from the backend's catalog (src/michelito/i18n/es_analysis.py).
  await expect(card).toContainText(`¿Es otro aporte a ${PEDRO}?`) // spanish-data
  await expect(card).not.toContainText('RD$ 1,500') // the small transfer is not proposed
  await card
    .getByRole('button', {
      name: literal(t('review.row.contributionLabel', { merchant: 'MB A 0000000066' }), {
        start: true,
      }),
    })
    .click()
  await expect(card).not.toContainText(t('review.kind.possibleContribution'))
  const kpis = page.getByRole('region', { name: t('summary.kpi.sectionLabel') })
  await expect(kpis.getByTestId('invested-note')).toHaveText(investedNote('RD$ 450,000'))
  await kpis.getByRole('link', { name: investedNote('RD$ 450,000') }).click()
  await expect(page).toHaveURL(/\/investments$/)
  await expect(page.getByRole('heading', { level: 1, name: t('investments.title') })).toBeVisible()
})

test('the list: one active and one closed, chips and search box', async ({ page }) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: t('shell.nav.label') })
    .getByRole('link', { name: t('shell.nav.investments') })
    .click()
  await expect(page).toHaveURL(/\/investments$/)

  await expect(page.getByTestId('investments-pending')).toHaveText(
    t('investments.figure.approx', { amount: 'RD$ 350,000' }),
  )
  // The credits are from 2025.
  await expect(page.getByTestId('investments-year')).toHaveText(
    t('investments.figure.approx', { amount: 'RD$ 0' }),
  )
  await expect(page.getByTestId('investments-active')).toHaveText(
    t('investments.figure.activeCount', { count: 1 }),
  )

  const chips = page.getByRole('group', { name: t('investments.chipsLabel') })
  const chip = (label: string) => ({ name: literal(label, { start: true }) })
  await expect(chips.getByRole('button', chip(t('investments.chip.active')))).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  const pedro = row(page, PEDRO)
  await expect(pedro).toContainText(t('investments.status.active'))
  const stats = pedro.getByTestId('investment-stats')
  await expect(stats).toContainText(stat(t('investments.stat.contributed'), 'RD$ 400,000'))
  await expect(stats).toContainText(stat(t('investments.stat.returned'), 'RD$ 50,000'))
  await expect(stats).toContainText(stat(t('investments.stat.returns'), 'RD$ 19,000'))
  await expect(stats).toContainText(
    new RegExp(`${escapeRegExp(t('investments.stat.rate'))}\\d+\\.\\d %`),
  )
  await expect(pedro).toContainText(
    t('investments.meta.lastCredit', { day: `${shortDay('2025-12-29')} 2025` }),
  )
  await expect(row(page, ANA_LOAN)).toHaveCount(0)

  await chips.getByRole('button', chip(t('investments.chip.closed'))).click()
  await expect(page).toHaveURL(/status=closed/)
  await expect(row(page, ANA_LOAN)).toContainText(t('investments.status.closed'))
  await expect(row(page, ANA_LOAN)).toContainText(stat(t('investments.stat.returns'), 'RD$ 2,000'))
  await expect(row(page, PEDRO)).toHaveCount(0)

  await chips.getByRole('button', chip(t('investments.chip.all'))).click()
  const titles = await list(page).getByRole('button').allTextContents()
  // Latest activity first: Pedro (29 Dec) before Ana (26 Dec).
  expect(titles.findIndex((text) => text.startsWith(PEDRO))).toBeLessThan(
    titles.findIndex((text) => text.startsWith(ANA_LOAN)),
  )
  const search = page.getByRole('searchbox', { name: t('investments.searchLabel') })
  await search.fill('ana')
  await expect(page).toHaveURL(/q=ana/)
  await expect(row(page, ANA_LOAN)).toBeVisible()
  await expect(row(page, PEDRO)).toHaveCount(0)
  await search.fill('300,000') // an amount
  await expect(row(page, PEDRO)).toBeVisible()
  await expect(row(page, ANA_LOAN)).toHaveCount(0)
  await chips.getByRole('button', chip(t('investments.chip.closed'))).click()
  await expect(
    page.getByText(
      t('investments.noneMatching', { none: t('investments.none.closed'), query: '300,000' }),
    ),
  ).toBeVisible()
})

test('a row expands; «Manage…» and «Back» return with it expanded', async ({ page }) => {
  await page.goto('/investments')
  const pedro = row(page, PEDRO)
  await expect(pedro).toHaveAttribute('aria-expanded', 'false')
  await pedro.click()
  await expect(pedro).toHaveAttribute('aria-expanded', 'true')
  await expect(page).toHaveURL(/investment=\d+/)
  const contributions = page.getByRole('region', {
    name: t('investments.row.contributionsLabel', { title: PEDRO }),
  })
  await expect(contributions).toContainText(
    t('links.linkedLabel', { merchant: 'MB A 0000000066', day: shortDay('2025-12-02') }),
  )
  await expect(contributions).toContainText('RD$ 100,000')
  await expect(
    page.getByRole('region', { name: t('investments.row.creditsLabel', { title: PEDRO }) }),
  ).toContainText(mixed('RD$ 50,000', 'RD$ 10,000'))
  const back = page.url()

  await page
    .getByRole('link', { name: t('investments.row.manageLabel', { title: PEDRO }) })
    .click()
  await expect(page).toHaveURL(/\/transactions\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/MB A 0000000066/)
  const panel = page.getByTestId('investment-panel')
  await expect(panel).toContainText(PEDRO)

  // Renaming and «Write off» (and undoing it) from its screen.
  await panel.getByLabel(t('links.investment.withWhom')).fill('Pedro Pérez') // spanish-data
  await panel.getByRole('button', { name: t('links.group.saveName') }).click()
  await expect(panel.getByRole('button', { name: t('links.group.saveName') })).toHaveCount(0)
  const lost = panel.getByRole('checkbox', { name: literal(t('links.investment.writeOff')) })
  await lost.click() // controlled: it changes when the server answers
  await expect(panel).toContainText(
    t('links.investment.heading', { status: t('investments.status.writtenOff') }),
  )
  await expect(lost).toBeChecked()
  await lost.click()
  await expect(panel).toContainText(
    t('links.investment.heading', { status: t('investments.status.active') }),
  )
  await expect(lost).not.toBeChecked()

  await page.getByRole('link', { name: t('links.page.back') }).click()
  await expect(page).toHaveURL(back)
  await expect(row(page, PEDRO)).toHaveAttribute('aria-expanded', 'true')
  await expect(row(page, PEDRO)).toBeFocused()
  await expect(row(page, PEDRO)).toContainText('Pedro Pérez') // spanish-data
})

test('at 390 px nothing scrolls sideways and touch targets are 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/investments?status=all')
  await row(page, PEDRO).click()
  await expect(
    page.getByRole('region', { name: t('investments.row.contributionsLabel', { title: PEDRO }) }),
  ).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const targets = page.getByRole('main').locator('button:visible, a:visible, input:visible')
  for (const target of await targets.all()) {
    const box = await target.boundingBox()
    expect(box?.height ?? 0, await target.evaluate((el) => el.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44)
  }

  // «To review» with a possible return (three buttons): the row wraps, it does not overflow.
  await page.route('**/api/review?**', (route) =>
    route.fulfill({
      json: [
        {
          kind: 'possible_return',
          fingerprint: 'made-up-return-fingerprint',
          day: '2025-12-30',
          month: DECEMBER,
          merchant: 'TRANSF PEDRO INVERSOR FICTICIO CON NOMBRE LARGO',
          description: 'TRANSF DE PEDRO INVERSOR FICTICIO CON NOMBRE LARGO',
          account_label: 'FICTICIO Cuenta de ahorro 888-1', // spanish-data
          amount_cents: 1_250_000,
          currency: 'DOP',
          amount_dop_cents: 1_250_000,
          reason: `¿Es un cobro de ${PEDRO}?`, // spanish-data: the backend's reason text
          reviewed: false,
          investment_id: 1,
        },
      ],
    }),
  )
  await page.goto(`/?month=${DECEMBER}`)
  const card = page.getByRole('region', { name: literal(t('summary.review.title')) })
  const actions = (['review.row.returnLabel', 'review.row.capitalLabel', 'review.row.notInvestmentLabel'] as const)
    .map((key) => escapeRegExp(startOf(t(key, { merchant: HOLE }))))
    .join('|')
  const buttons = card.getByRole('button', { name: new RegExp(`^(${actions})`) })
  await expect(buttons).toHaveCount(3)
  for (const button of await buttons.all()) {
    const box = (await button.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
  }
  const reviewOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(reviewOverflow).toBeLessThanOrEqual(0)
  await page.unroute('**/api/review?**')

  // The investment's screen does not overflow either.
  await page.goto('/investments?status=all')
  await row(page, PEDRO).click()
  await page
    .getByRole('link', { name: t('investments.row.manageLabel', { title: PEDRO }) })
    .click()
  await expect(page.getByTestId('investment-panel')).toBeVisible()
  const managed = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(managed).toBeLessThanOrEqual(0)
})
