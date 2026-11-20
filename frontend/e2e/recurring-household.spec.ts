import { expect, test, type Page } from '@playwright/test'
import { literal, t } from './text'

// The `--household` server of tests/e2e_server.py (made-up data and providers): a made-up
// phone company with four names (TELFIC PAGO, IBANKING, P and WB; January in two payments) and
// a top-up and a purchase in its store (TELFIC AGORA), AGUA FICTICIA (without a provider) and
// the made-up water utility of the list without payments, ALQUILER FICTICIO (housing), a loan
// with an extra payment in January and a loose SEGURO HOGAR. Each test undoes in the Log what it
// did: none depends on another. Log lines are written by the backend catalog: data here.
const PHONE = 'Telefónica Ficticia' // spanish-data: provider name
const WATER = 'AGUA FICTICIA'
const WATER_PROVIDER = 'Acueducto Ficticio' // spanish-data: provider name
const INSURANCE = 'SEGURO HOGAR'
const RENT = 'ALQUILER FICTICIO'
const HOUSING = t('recurring.group.housing')
// The group name the API sends with a transaction's recurring state.
const HOUSING_FROM_API = 'Vivienda' // spanish-data: group label from the API
const UTILITIES_FROM_API = 'Servicios' // spanish-data: group label from the API
const TRANSACTION_LIST = t('transactions.list.label')

function markName(name: string): string {
  return t('recurring.row.markNamed', { name })
}

function includes(members: string): string {
  return t('recurring.row.includes', { members })
}

function row(page: Page, name: string) {
  return page.getByRole('listitem').filter({
    has: page.getByRole('button', { name: markName(name), exact: true }),
  })
}

async function openActions(page: Page, name: string) {
  await page.getByRole('button', { name: markName(name), exact: true }).click()
  return page.getByRole('group', { name: t('recurring.actions.label', { name }), exact: true })
}

/** Undoes in the Log the entry "subject · — → after" (it searches for it by `search`). */
async function undoInLog(page: Page, search: string, subject: string, after: string) {
  await page.goto('/log')
  await page.getByRole('searchbox', { name: t('log.filter.search') }).fill(search)
  const line = `${subject} · — → ${after}`
  await page.getByRole('button', { name: t('log.row.undoNamed', { name: line }), exact: true }).click()
  // The same row turns undone and offers «Rehacer».
  await expect(
    page.getByRole('button', { name: t('log.row.redoNamed', { name: line }), exact: true }),
  ).toBeVisible()
}

test('groups go housing, loans, utilities; the provider joins its names', async ({ page }) => {
  await page.goto('/recurring')
  const titles = page.getByRole('main').getByRole('heading', { level: 2 })
  await expect(titles.nth(0)).toHaveText(literal(HOUSING, { start: true }))
  await expect(titles.nth(1)).toHaveText(literal(t('recurring.group.loans'), { start: true }))
  await expect(titles.nth(2)).toHaveText(literal(t('recurring.group.utilities'), { start: true }))
  const phone = row(page, PHONE)
  await expect(phone).toContainText(includes('TELFIC IBANKING, TELFIC P, TELFIC PAGO, TELFIC WB'))
  await expect(phone).toContainText(t('recurring.badge.variable'))
  await expect(phone).toContainText('RD$ 1,500')
  await expect(row(page, 'AUT PAGO 0000000088')).toContainText(
    t('recurring.extras', { amount: 'RD$ 30,000' }),
  )
  await expect(row(page, RENT)).toBeVisible()
  await expect(page.getByRole('main')).not.toContainText('RECARGA')
  await expect(page.getByRole('main')).not.toContainText('AGORA')
})

test('"Group…" changes the rent\'s group and is undone in the Log', async ({ page }) => {
  await page.goto('/recurring')
  const actions = await openActions(page, RENT)
  await actions.getByRole('button', { name: t('recurring.actions.group') }).click()
  await actions
    .getByRole('combobox', { name: t('recurring.actions.groupLabel'), exact: true })
    .selectOption('other')
  await actions.getByRole('button', { name: t('recurring.actions.saveGroup') }).click()
  const others = page.getByRole('region', {
    name: literal(t('recurring.group.other'), { start: true }),
  })
  await expect(others.getByRole('button', { name: markName(RENT), exact: true })).toBeVisible()

  await undoInLog(page, RENT, RENT, 'sin marca, en Otros recurrentes') // spanish-data
  await page.goto('/recurring')
  const housing = page.getByRole('region', { name: literal(HOUSING, { start: true }) })
  await expect(housing.getByRole('button', { name: markName(RENT), exact: true })).toBeVisible()
})

test('"Join with…" joins the water with the utility and is undone in the Log', async ({
  page,
}) => {
  await page.goto('/recurring')
  const actions = await openActions(page, WATER)
  await actions.getByRole('button', { name: t('recurring.actions.join') }).click()
  await actions
    .getByRole('combobox', { name: t('recurring.actions.joinLabel'), exact: true })
    .selectOption({ label: WATER_PROVIDER })
  await actions.getByRole('button', { name: t('recurring.actions.joinSubmit'), exact: true }).click()
  await expect(row(page, WATER_PROVIDER)).toContainText(includes(WATER))
  await expect(page.getByRole('button', { name: markName(WATER), exact: true })).toHaveCount(0)

  await undoInLog(page, WATER_PROVIDER, `${WATER} → ${WATER_PROVIDER}`, `con ${WATER_PROVIDER}`) // spanish-data
  await expect(page.getByRole('main')).toContainText(t('log.kind.recurring_union'))
  await page.goto('/recurring')
  await expect(row(page, WATER)).toBeVisible()
  await expect(page.getByRole('button', { name: markName(WATER_PROVIDER) })).toHaveCount(0)
})

test('"Separate" takes a name out of the provider and is undone in the Log', async ({ page }) => {
  await page.goto('/recurring')
  const actions = await openActions(page, PHONE)
  await actions
    .getByRole('button', { name: t('recurring.actions.separateNamed', { member: 'TELFIC P' }), exact: true })
    .click()
  await expect(row(page, PHONE)).toContainText(includes('TELFIC IBANKING, TELFIC PAGO, TELFIC WB'))

  await undoInLog(page, 'TELFIC P', `TELFIC P · fuera de ${PHONE}`, 'por separado') // spanish-data
  await page.goto('/recurring')
  await expect(row(page, PHONE)).toContainText('TELFIC IBANKING, TELFIC P, TELFIC PAGO')
})

test('"It is recurring…" from the detail marks a loose charge and takes it to Recurring', async ({
  page,
}) => {
  await page.goto('/transactions?month=2026-01')
  const list = page.getByRole('region', { name: TRANSACTION_LIST })
  await list.getByRole('button', { name: new RegExp(INSURANCE) }).click()
  const section = page
    .getByRole('complementary')
    .getByRole('region', { name: t('transactions.recurring.title') })
  await section.getByRole('button', { name: t('transactions.recurring.open') }).click()
  await section.getByRole('radio', { name: t('transactions.recurring.yearly') }).check()
  await section
    .getByRole('combobox', { name: t('transactions.recurring.group'), exact: true })
    .selectOption('housing')
  await section.getByRole('button', { name: t('transactions.recurring.submit') }).click()
  await expect(section.getByTestId('recurring-state')).toHaveText(
    `${t('transactions.recurring.state', { name: INSURANCE })} · ${HOUSING_FROM_API}`,
  )

  await section.getByRole('link', { name: t('transactions.recurring.see') }).click()
  await expect(page).toHaveURL(/\/recurring$/)
  const housing = page.getByRole('region', { name: literal(HOUSING, { start: true }) })
  await expect(housing.getByRole('listitem').filter({ hasText: INSURANCE })).toContainText(
    t('recurring.cadence.yearly'),
  )

  await undoInLog(page, INSURANCE, INSURANCE, 'es recurrente, anual, en Vivienda') // spanish-data
  await page.goto('/recurring')
  await expect(page.getByRole('button', { name: markName(INSURANCE) })).toHaveCount(0)
})

test("the detail of a provider's payment says it is already recurring", async ({ page }) => {
  await page.goto('/transactions?month=2026-01')
  const list = page.getByRole('region', { name: TRANSACTION_LIST })
  await list.getByRole('button', { name: /TELFIC IBANKING/ }).click()
  const section = page
    .getByRole('complementary')
    .getByRole('region', { name: t('transactions.recurring.title') })
  await expect(section.getByTestId('recurring-state')).toHaveText(
    `${t('transactions.recurring.state', { name: PHONE })} · ${UTILITIES_FROM_API}`,
  )
  await expect(section.getByRole('button', { name: t('transactions.recurring.open') })).toHaveCount(0)
})

test('at 390 px Recurring does not scroll sideways and touch targets are 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/recurring')
  await expect(page.getByRole('heading', { level: 1, name: t('recurring.title') })).toBeVisible()
  const actions = await openActions(page, PHONE)
  await actions.getByRole('button', { name: t('recurring.actions.join') }).click()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const buttons = actions.getByRole('button')
  for (const button of await buttons.all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  const select = actions.getByRole('combobox', { name: t('recurring.actions.joinLabel'), exact: true })
  expect((await select.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
})
