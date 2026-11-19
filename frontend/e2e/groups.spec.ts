import { expect, test, type Page } from '@playwright/test'
import { escapeRegExp, literal, t } from './text'

// Made-up data from tests/e2e_server.py, February 2026: on the VISA DEMO a supermarket (RD$
// 3,120.75, day 3), a garage (RD$ 1,500, day 4) and a cinema (RD$ 640, day 7); on the checking
// account, a transfer from Carola of RD$ 3,760.75 (day 9) that pays the supermarket and the
// cinema. At the end the group is undone: the other tests see the usual totals.
const FEBRUARY = '2026-02'
const GROUP = 'Carola y Rafael' // spanish-data: who the group is with, typed by the test

// Where a value goes inside a catalog message, to match it with a pattern.
const HOLE = '\u0000'

/** The catalog `text` (with HOLE where a value goes) as an anchored RegExp, `source` in the hole. */
function withHole(text: string, source: string): RegExp {
  return new RegExp(`^${text.split(HOLE).map(escapeRegExp).join(source)}$`)
}

/** The start of a catalog message, up to where its value goes. */
function startOf(text: string): string {
  return text.split(HOLE)[0]
}

const removeFromGroup = (merchant: string) =>
  withHole(t('links.group.removeExpenseOf', { merchant: HOLE }), `${escapeRegExp(merchant)}.*`)

const heading = (count: number) =>
  t('links.group.heading', { expenses: t('links.expenseCount', { count }) })

/** The figures line of the group: your share, reimbursed and owed (each label and amount). */
const sharedLine = (share: string, reimbursed: string, owed: string) =>
  `${t('links.stat.yourShare')}${share}${t('links.stat.reimbursed')}${reimbursed}` +
  `${t('links.stat.owed')}${owed}`

const overStart = startOf(t('links.warning.over', { amount: HOLE }))

test.describe.configure({ mode: 'serial' })

async function openRow(page: Page, name: RegExp) {
  await page.goto(`/transactions?month=${FEBRUARY}`)
  const row = page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .getByRole('button', { name })
  await row.click()
  return row
}

/** Opens the row's link screen from the «Shared» or «Reimbursement» line of the panel. */
async function openScreen(page: Page, name: RegExp, section = t('links.summary.sharedTitle')) {
  await openRow(page, name)
  // On a phone the detail manages links in sheets: the screen opens by its address.
  if ((await page.locator('[data-mobile-detail]').count()) > 0) {
    const fingerprint = new URL(page.url()).searchParams.get('tx')
    await page.goto(`/transactions/${encodeURIComponent(fingerprint!)}`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(name)
    return
  }
  await page
    .getByRole('complementary')
    .getByRole('region', { name: section })
    .getByRole('button', {
      name: new RegExp(
        `${escapeRegExp(t('links.action.share'))}|${escapeRegExp(t('links.action.manage'))}`,
      ),
    })
    .click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(name)
}

const expenses = (page: Page) =>
  page.getByRole('list', { name: t('links.group.expensesList') })

test('«Share…» creates a group with «With whom»', async ({ page }) => {
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  await page.getByRole('radio', { name: t('transactions.split.other') }).check()
  await page.getByLabel(t('links.share.withWhom')).fill(GROUP)
  await page.getByRole('button', { name: t('links.share.mark') }).click()
  await expect(page.getByRole('heading', { level: 2, name: heading(1) })).toBeVisible()
  await expect(page.getByTestId('shared-group')).toContainText(GROUP)
  await expect(page.getByTestId('shared-line')).toHaveText(
    sharedLine('RD$ 0', 'RD$ 0', 'RD$ 3,121'),
  )
})

test('«Share…» on the cinema adds it to the group with the split of the last expense', async ({
  page,
}) => {
  await openScreen(page, /CINE INVENTADO/)
  const tabs = page.getByRole('tablist', { name: t('links.share.how') })
  await expect(tabs.getByRole('tab', { name: t('links.share.newGroup') })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await tabs.getByRole('tab', { name: t('links.share.joinGroup') }).click()
  await expect(tabs.getByRole('tab', { name: t('links.share.joinGroup') })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  const open = page.getByRole('list', { name: t('links.share.openGroups') })
  await expect(open).toContainText(
    t('links.group.label', {
      title: GROUP,
      status: t('links.group.owed', { amount: 'RD$ 3,121' }),
    }),
  )
  await open.getByRole('button', { name: t('links.share.joinTo', { title: GROUP }) }).click()
  await expect(page.getByRole('radio', { name: t('transactions.split.other') })).toBeChecked()
  await page.getByRole('button', { name: t('links.group.addToGroup') }).click()

  await expect(page.getByRole('heading', { level: 2, name: heading(2) })).toBeVisible()
  await expect(page.getByTestId('shared-line')).toHaveText(
    sharedLine('RD$ 0', 'RD$ 0', 'RD$ 3,761'),
  )
  // The open transaction is highlighted in the group's list.
  const current = expenses(page).locator('[aria-current="true"]')
  await expect(current).toHaveCount(1)
  await expect(current).toContainText('CINE INVENTADO')
})

test('Pending shows one row per group', async ({ page }) => {
  await page.goto('/pending')
  const owed = page.getByRole('region', { name: t('pending.figure.owed') })
  const group = owed.getByRole('link', { name: literal(GROUP) })
  await expect(group).toHaveCount(1)
  await expect(group).toContainText(t('links.expenseCount', { count: 2 }))
  await expect(group).toContainText('RD$ 3,761')
  await expect(owed.getByRole('link', { name: /SUPERMERCADO|CINE INVENTADO/ })).toHaveCount(0)

  await group.click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/SUPERMERCADO FICTICIO/)
  await expect(page.getByRole('heading', { level: 2, name: heading(2) })).toBeVisible()
  // The group panel: the people («With whom») and the name, with examples in the label.
  await expect(page.getByLabel(t('links.group.people'))).toHaveValue(GROUP)
  await expect(page.getByLabel(t('links.group.name'))).toHaveValue('')
})

test('the transfer suggested by name settles both', async ({ page }) => {
  const transfer = await openRow(page, /TRANSF CAROLA/)
  await expect(transfer).toContainText(t('links.badge.suggestedReimbursement'))
  const detail = page.getByRole('complementary')
  await expect(detail).toContainText(t('links.shortcut.reimbursement', { what: GROUP }))
  await detail.getByRole('button', { name: t('links.shortcut.link') }).click()
  await expect(detail.getByTestId('link-summary-reimbursement')).toHaveText(
    t('links.summary.reimbursementOf', {
      what: t('links.group.label', { title: GROUP, status: t('links.group.settled') }),
    }),
  )
  await expect(transfer).toContainText(t('links.badge.reimbursement'))

  await detail
    .getByRole('region', { name: t('links.summary.reimbursementTitle') })
    .getByRole('button', { name: t('links.action.manage') })
    .click()
  const settled = t('links.expense.settled')
  await expect(page.getByTestId('expense-status')).toHaveText([settled, settled])
  await expect(page.getByText(literal(overStart, { start: true }))).toHaveCount(0)
  const current = page
    .getByRole('list', { name: t('links.group.refunds') })
    .locator('[aria-current="true"]')
  await expect(current).toContainText('TRANSF CAROLA')
})

test('reimbursing too much warns; the missing expense comes first and the warning goes away', async ({
  page,
}) => {
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  // They also paid the garage, in cash: it is too much until the expense is added.
  await page.getByRole('button', { name: t('links.group.addRefund') }).click()
  await page.getByRole('button', { name: t('links.refund.paidElsewhere') }).click()
  await page.getByLabel(literal(startOf(t('links.refund.amount', { currency: HOLE })), { start: true })).fill('1500')
  await page.getByRole('button', { name: t('links.refund.save') }).click()
  await expect(
    page.getByText(literal(t('links.warning.over', { amount: 'RD$ 1,500' }), { start: true })),
  ).toBeVisible()

  await page.getByRole('button', { name: t('links.group.addExpense') }).click()
  const options = page.getByRole('list', { name: t('links.group.candidates') })
  // The one that fits what was reimbursed too much comes first, without searching for it.
  await expect(options.getByRole('listitem').first()).toContainText('TALLER')
  await options
    .getByRole('button', {
      name: literal(t('links.addMerchant', { merchant: 'TALLER' }), { start: true }),
    })
    .click()
  await expect(page.getByRole('radio', { name: t('transactions.split.other') })).toBeChecked()
  await page.getByRole('button', { name: t('links.group.addToGroup') }).click()

  await expect(page.getByRole('heading', { level: 2, name: heading(3) })).toBeVisible()
  const settled = t('links.expense.settled')
  await expect(page.getByTestId('expense-status')).toHaveText([settled, settled, settled])
  await expect(page.getByText(literal(overStart, { start: true }))).toHaveCount(0)
  await expect(page.getByTestId('shared-line')).toHaveText(
    sharedLine('RD$ 0', 'RD$ 5,261', 'RD$ 0'),
  )
})

test('at 390 px the group screen fits without sideways scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  await expect(page.getByTestId('shared-group')).toBeVisible()
  await page.getByRole('button', { name: t('links.group.addRefund') }).click()
  await page.getByRole('button', { name: t('links.refund.paidElsewhere') }).click()
  await expect(page.getByLabel(t('links.refund.place'))).toBeVisible()
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})

test('«Remove from group»: the reimbursements stay; the last one deletes the group', async ({
  page,
}) => {
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  await page.getByRole('button', { name: removeFromGroup('TALLER') }).click()
  await expect(page.getByRole('heading', { level: 2, name: heading(2) })).toBeVisible()
  await expect(
    page.getByText(literal(t('links.warning.over', { amount: 'RD$ 1,500' }), { start: true })),
  ).toBeVisible()
  await expect(page.getByRole('list', { name: t('links.group.refunds') })).toContainText(
    'TRANSF CAROLA',
  )

  await page.getByRole('button', { name: removeFromGroup('CINE INVENTADO') }).click()
  await expect(page.getByRole('heading', { level: 2, name: heading(1) })).toBeVisible()
  await page.getByRole('button', { name: removeFromGroup('SUPERMERCADO FICTICIO') }).click()
  const confirm = page.getByRole('alertdialog', { name: t('links.group.removeLast') })
  await expect(confirm).toContainText(t('links.group.lastExpense'))
  // Focus enters the dialog and, on cancel, returns to the button.
  await expect(confirm).toBeFocused()
  await confirm.getByRole('button', { name: t('links.cancel') }).click()
  const last = page.getByRole('button', { name: removeFromGroup('SUPERMERCADO FICTICIO') })
  await expect(last).toBeFocused()
  await last.click()
  await confirm.getByRole('button', { name: t('links.group.removeLastConfirm') }).click()
  await expect(page.getByRole('heading', { level: 2, name: t('links.share.title') })).toBeVisible()

  const transfer = await openRow(page, /TRANSF CAROLA/)
  await expect(transfer).not.toContainText(t('links.badge.reimbursement'))
})

/** "Could not load <what>:" — the start of a load failure, before the error itself. */
const loadFailure = (what: string) =>
  startOf(t('links.loadFailure', { what, error: HOLE })).trimEnd()

test('when a list does not load, it says so instead of showing it empty', async ({ page }) => {
  await page.route('**/api/shared/open', (route) => route.fulfill({ status: 500, body: 'x' }))
  await page.route('**/reimbursement-candidates', (route) =>
    route.fulfill({ status: 500, body: 'x' }),
  )
  await openScreen(page, /CINE INVENTADO/)
  await expect(page.getByRole('alert')).toContainText(loadFailure(t('links.what.groups')))

  await openScreen(page, /TRANSF CAROLA/, t('links.summary.reimbursementTitle'))
  await expect(page.getByRole('alert')).toContainText(loadFailure(t('links.what.groups')))
})

test('when the expense or credit picker does not load, it says so', async ({ page }) => {
  await openScreen(page, /CINE INVENTADO/)
  await page.getByLabel(t('transactions.split.peopleCount')).fill('2')
  await page.getByRole('button', { name: t('links.share.mark') }).click()
  await expect(page.getByRole('heading', { level: 2, name: heading(1) })).toBeVisible()
  await page.route('**/expense-candidates', (route) => route.fulfill({ status: 500, body: 'x' }))
  await page.route('**/credit-candidates', (route) => route.fulfill({ status: 500, body: 'x' }))
  await page.getByRole('button', { name: t('links.group.addExpense') }).click()
  await expect(page.getByRole('alert')).toContainText(loadFailure(t('links.what.expenses')))
  await page.getByRole('button', { name: t('links.group.addRefund') }).click()
  await expect(
    page.getByRole('alert').filter({ hasText: t('links.what.credits') }),
  ).toContainText(loadFailure(t('links.what.credits')))

  // Leaves the cinema as it was.
  await page.getByRole('button', { name: removeFromGroup('CINE INVENTADO') }).click()
  await page.getByRole('button', { name: t('links.group.removeLastConfirm') }).click()
  await expect(page.getByRole('heading', { level: 2, name: t('links.share.title') })).toBeVisible()
})
