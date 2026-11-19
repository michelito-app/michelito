import { expect, test, type Page } from '@playwright/test'
import { escapeRegExp, t } from './text'

// The `--household` server of tests/e2e_server.py (made-up data): December 2025 is the last
// complete month (the usual amounts come from it), the rent is RD$ 25,000 and January's
// "MARBETE FICTICIO" is marked as a yearly recurring charge, so Budget suggests a reserve for
// it. "Today" is February 20, 2026. Each test undoes in the Log what it did: none depends on
// another. The log lines themselves are written by the backend catalog, so they are data here.
const TAX = 'MARBETE FICTICIO'
const RENT = 'Vivienda' // spanish-data: seeded category
const SCHOOL = 'Colegio ficticio' // spanish-data: typed reserve name
const JANUARY = 'enero' // spanish-ui: month name built with Intl
const MARCH_2026 = 'marzo 2026' // spanish-ui: month phrase built with Intl
const BUDGET_LOG = 'Presupuesto' // spanish-data: backend log target
const HOLE = '\u0000'

/** An anchored RegExp for `text` (built with HOLE params), each HOLE matching `\d+`. */
function digits(text: string): RegExp {
  return new RegExp(`^${text.split(HOLE).map(escapeRegExp).join('\\d+')}$`)
}

/** Undoes in the Log the entry whose undo button names `line` (it searches for it first). */
async function undo(page: Page, search: string, line: string | RegExp) {
  await page.goto('/log')
  await page.getByRole('searchbox', { name: t('log.filter.search') }).fill(search)
  const name = typeof line === 'string' ? t('log.row.undoNamed', { name: line }) : line
  const button = page.getByRole('button', { name, exact: typeof line === 'string' })
  await button.first().click()
  await expect(page.getByRole('main')).toContainText(t('log.undone', { line: '' }).trim())
}

const ACTIVATED = digits(
  t('log.row.undoNamed', {
    name: `${BUDGET_LOG} · sin activar → ${HOLE} categorías, ${HOLE} con tope`, // spanish-data
  }),
)

const ACTIVATE = t('budget.activate.button')
const NEW_RESERVE = t('budget.reserves.new')
const RESERVES = t('budget.reserves.title')
const SUGGESTIONS = t('budget.suggestions.label')
const UPCOMING = t('summary.budgetCard.upcomingLabel')

async function activate(page: Page) {
  await page.goto('/budget?month=2025-12')
  await page.getByRole('button', { name: ACTIVATE }).click()
  await expect(page.getByRole('listitem', { name: RENT, exact: true })).toBeVisible()
}

test('activating the budget, editing a cap and seeing a category over it', async ({ page }) => {
  await activate(page)
  const rent = page.getByRole('listitem', { name: RENT, exact: true })
  // It starts with the rounded usual amount (December's rent).
  const spent = t('budget.spent.ofCap', { spent: 'RD$ 25,000', cap: 'RD$ 25,000' })
  await expect(rent).toContainText(spent)
  await rent.getByRole('button', { name: t('budget.line.editLabel', { category: RENT }) }).click()
  await rent.getByRole('textbox', { name: t('budget.cap.inputLabel', { category: RENT }) }).fill('20000')
  await rent.getByRole('button', { name: t('budget.cap.save') }).click()
  await expect(rent).toContainText(
    t('budget.spent.ofCap', { spent: 'RD$ 25,000', cap: 'RD$ 20,000' }) +
      t('budget.line.overBy', { amount: 'RD$ 5,000' }),
  )
  await expect(rent).toContainText(t('budget.line.manual'))
  // The one that goes over the most comes first.
  const lines = page
    .getByRole('region', { name: t('budget.categories.title') })
    .getByTestId('budget-line')
  await expect(lines.first()).toHaveAccessibleName(RENT)

  // The Summary card counts the categories over their cap.
  await page.goto('/?month=2025-12')
  const card = page.getByRole('region', { name: t('summary.budgetCard.title'), exact: true })
  // "1 category over (+RD$": the overview without its budget prefix and without the rest of
  // the amount.
  const over = t('budget.overview.over', { count: 1, amount: 'RD$' })
  const overText = over.slice(over.indexOf(': ') + 2, -1)
  await expect(card.getByTestId('budget-status')).toContainText(new RegExp(escapeRegExp(overText)))

  await undo(page, RENT, `${RENT} · tope RD$ 25,000 → tope RD$ 20,000`) // spanish-data
  await undo(page, BUDGET_LOG, ACTIVATED)
  await page.goto('/budget')
  await expect(page.getByRole('button', { name: ACTIVATE })).toBeVisible()
})

test('creating a reserve from a suggestion and linking an expense to it', async ({ page }) => {
  await page.goto('/budget')
  const suggestions = page.getByRole('group', { name: SUGGESTIONS })
  await expect(suggestions).toContainText(
    t('budget.suggestion', { name: TAX, amount: 'RD$ 3,400', month: JANUARY }),
  )
  await suggestions.getByRole('button', { name: t('budget.suggestions.createLabel', { name: TAX }) }).click()
  const reserves = page.getByRole('region', { name: RESERVES })
  const reserve = reserves.getByRole('listitem', { name: TAX, exact: true })
  await expect(reserve).toContainText(t('budget.reserve.perMonth', { amount: 'RD$ 300' }))
  await expect(reserve).toContainText(t('budget.scheduleText.yearly', { month: JANUARY }))
  await expect(page.getByRole('group', { name: SUGGESTIONS })).toHaveCount(0)

  // "It belongs to a reserve…" from the expense's detail.
  await page.goto('/transactions?month=2026-01')
  const list = page.getByRole('region', { name: t('transactions.list.label') })
  await list.getByRole('button', { name: new RegExp(TAX) }).click()
  const section = page
    .getByRole('complementary')
    .getByRole('region', { name: t('transactions.reserve.title') })
  await section.getByRole('button', { name: t('transactions.reserveBatch.placeholder') }).click()
  await section
    .getByRole('combobox', { name: t('transactions.reserve.title'), exact: true })
    .selectOption({ index: 0 })
  await section.getByRole('button', { name: t('transactions.reserve.link'), exact: true }).click()
  await expect(section.getByTestId('reserve-state')).toContainText(
    t('transactions.reserve.covered', { name: TAX }).split(':')[0],
  )
  await expect(section).toContainText(t('transactions.reserve.removeFirst'))

  await page.goto('/budget')
  const linked = page
    .getByRole('region', { name: RESERVES })
    .getByRole('listitem', { name: TAX, exact: true })
  // The member line ends in the "covered by the reserve" note.
  const covered = t('budget.reserve.memberLine', { day: '', amount: '' }).split(' · ').at(-1)!
  await expect(linked).toContainText(covered)
  await expect(linked).toContainText(t('budget.year', { spent: 'RD$ 3,400', estimated: 'RD$ 3,400' }))

  await undo(page, TAX, `${TAX} · — → cubierto por «${TAX}»`) // spanish-data
  await undo(page, TAX, `${TAX} · — → RD$ 3,400 · cada año en enero`) // spanish-data
  await page.goto('/budget')
  await expect(
    page.getByRole('button', { name: t('budget.suggestions.createLabel', { name: TAX }) }),
  ).toBeVisible()
})

test('a reserve due soon shows in the Summary\'s "Upcoming large expenses"', async ({ page }) => {
  await page.goto('/budget')
  await page.getByRole('button', { name: NEW_RESERVE }).click()
  const form = page.getByRole('form', { name: t('budget.form.newLabel') })
  await form.getByRole('textbox', { name: t('budget.form.nameLabel') }).fill(SCHOOL)
  await form.getByRole('textbox', { name: t('budget.form.amount') }).fill('45000')
  await form
    .getByRole('combobox', { name: t('budget.form.categoryLabel') })
    .selectOption('Educación') // spanish-data: seeded category
  await form.getByRole('radio', { name: t('budget.schedule.once') }).check()
  await form.getByLabel(t('budget.form.dueLabel')).fill('2026-03')
  await form.getByRole('button', { name: t('budget.form.create') }).click()
  const reserve = page.getByRole('listitem', { name: SCHOOL, exact: true })
  await expect(reserve).toContainText(t('budget.scheduleText.once', { month: MARCH_2026 }))

  await page.goto('/')
  const upcoming = page.getByRole('group', { name: UPCOMING })
  await expect(upcoming).toContainText(SCHOOL)
  await expect(upcoming).toContainText('RD$ 45,000')
  // The net figure says what is left after setting aside (the main number does not change).
  await expect(page.getByTestId('reserves-note')).toContainText(
    t('budget.afterReserves', { monthly: 'RD$ 22,500', left: '' }).split(': ')[0],
  )

  await undo(page, SCHOOL.split(' ')[0], `${SCHOOL} · — → RD$ 45,000 · una vez, en 2026-03`) // spanish-data
  await page.goto('/')
  await expect(page.getByRole('group', { name: UPCOMING })).toContainText(
    t('summary.budgetCard.noUpcoming'),
  )
})

test('at 390 px Budget does not scroll sideways and touch targets are 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await activate(page)
  await page.getByRole('button', { name: NEW_RESERVE }).click()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const buttons = page.getByRole('main').getByRole('button')
  const count = await buttons.count()
  expect(count).toBeGreaterThan(5)
  for (let i = 0; i < count; i++) {
    const box = await buttons.nth(i).boundingBox()
    if (box) expect(box.height, await buttons.nth(i).innerText()).toBeGreaterThanOrEqual(44)
  }
  await undo(page, BUDGET_LOG, ACTIVATED)
})
