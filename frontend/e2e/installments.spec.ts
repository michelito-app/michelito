import { expect, test, type Locator, type Page } from '@playwright/test'
import { t } from './text'

// Installment plans on their own server (tests/e2e_server.py --installments: a made-up US$ 150
// store charge on the VISA DEMO in December, January and February). From February's charge, "It
// is an installment…" lists the two earlier ones (it is installment 3); the plan can be for a
// new person; the rows say "cuota n/6"; the Cuotas page shows the plan's card, which can be
// edited and deleted; and "New plan" starts one from a picked charge. Desktop and an iPhone's
// size (WebKit).
const MONTH = '2026-02'
const MERCHANT = 'TIENDA COM'
const PLAN = 'Phone (Store)'
const RENAMED = 'Phone (Store) 2'
const PERSON = 'Sam Example'
const WRITE = { 'X-Michelito': '1' }
const LAST_MONTH = 'mayo 2026' // spanish-ui (December + 5 months)
const LAST_MONTH_12 = 'noviembre 2026' // spanish-ui (December + 11 months)

test.describe.configure({ mode: 'serial' })

// Every test starts without plans (the server's database lives across specs and projects).
test.beforeEach(async ({ request }) => {
  const plans = (await (await request.get('/api/installments')).json()) as { id: number }[]
  for (const plan of plans) {
    expect((await request.delete(`/api/installments/${plan.id}`, { headers: WRITE })).ok()).toBe(
      true,
    )
  }
})

function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 1280) < 768
}

function rows(page: Page): Locator {
  return page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .locator('[data-fingerprint]')
}

function detail(page: Page): Locator {
  return isPhone(page) ? page.locator('[data-mobile-detail]') : page.getByRole('complementary')
}

function formSheet(page: Page): Locator {
  return page.getByRole('dialog', { name: t('installments.form.title') })
}

/** Opens "It is an installment…" from the open detail: a button of its section on a wide
 * screen, a row of "More actions" on a phone. */
async function openForm(page: Page): Promise<Locator> {
  const panel = detail(page)
  if (isPhone(page)) {
    await panel.getByRole('button', { name: t('installments.detail.title') }).click()
  } else {
    await panel.getByRole('button', { name: t('installments.detail.create') }).click()
  }
  const form = formSheet(page)
  await expect(form).toBeVisible()
  return form
}

/** The Cuotas page through the menu (on a phone, inside "More"). */
async function goToInstallments(page: Page): Promise<void> {
  if (isPhone(page)) {
    await page.getByRole('button', { name: t('shell.nav.more'), exact: true }).click()
    await page
      .getByRole('dialog', { name: t('shell.nav.moreTitle') })
      .getByRole('link', { name: t('shell.nav.installments') })
      .click()
  } else {
    await page
      .getByRole('navigation', { name: t('shell.nav.label') })
      .getByRole('link', { name: t('shell.nav.installments') })
      .click()
  }
  await expect(page).toHaveURL(/\/installments$/)
  await expect(
    page.getByRole('heading', { level: 1, name: t('loans.page.title') }),
  ).toBeVisible()
}

function summary(paid: number, count: number, amount: string, month: string): string {
  return t('installments.plan.summary', { paid, count, amount, month })
}

async function expectFits(page: Page, box: Locator): Promise<void> {
  const size = await box.boundingBox()
  expect(size).not.toBeNull()
  expect(size!.x + size!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
}

test('a plan for a new person, made from a charge, shows on Cuotas and can be edited and deleted', async ({
  page,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  const row = rows(page).filter({ hasText: MERCHANT })
  await expect(row).toHaveCount(1)
  await expect(row.getByTestId('installment-tag')).toHaveCount(0)
  await row.click()

  // The short form: which installment it is comes from the two earlier charges, listed checked.
  const form = await openForm(page)
  await expect(form.getByTestId('installment-position')).toHaveText(
    t('installments.form.position', { number: 3, count: '6' }),
  )
  await expect(form.getByLabel(t('installments.form.number'))).toHaveCount(0)
  const earlier = form.getByTestId('installment-earlier')
  await expect(earlier.getByRole('checkbox')).toHaveCount(2)
  await expect(earlier.getByTestId('installment-earlier-number')).toHaveText([
    t('installments.form.earlierNumber', { number: 1 }),
    t('installments.form.earlierNumber', { number: 2 }),
  ])
  await expect(form.getByLabel(t('installments.form.count'))).toHaveValue('6')
  const owner = form.getByLabel(t('installments.form.owner'))
  await expect(owner).toHaveValue('me')
  await owner.selectOption('new')
  await form.getByLabel(t('installments.form.newName')).fill(PERSON)
  await form.getByLabel(t('installments.form.name')).fill(PLAN)
  await expectFits(page, form)
  await form.getByRole('button', { name: t('installments.form.submit') }).click()
  await expect(form).toHaveCount(0)

  const linked = t('installments.detail.linked', { number: 3, count: 6, name: PLAN })
  const panel = detail(page)
  if (isPhone(page)) {
    await expect(panel.getByTestId('mobile-link-installment')).toContainText(linked)
  } else {
    await expect(panel.getByTestId('installment-linked')).toHaveText(linked)
  }

  // The rows: January (listed before February) is installment 2.
  const tag = (number: number) => t('installments.row.tag', { number, count: 6, name: PLAN })
  await page.goto('/transactions?month=2026-01')
  await expect(rows(page).filter({ hasText: MERCHANT }).getByTestId('installment-tag')).toHaveText(
    tag(2),
  )

  // Cuotas: the plan's card with what is left, each installment's state and whom it is for.
  await goToInstallments(page)
  const card = page.getByTestId('installment-plans').getByTestId('installment-plan')
  await expect(card).toHaveCount(1)
  await expect(card.getByRole('heading', { name: PLAN })).toBeVisible()
  await expect(card.getByTestId('installment-summary')).toHaveText(
    summary(3, 6, 'US$ 450.00', LAST_MONTH),
  )
  await expect(card.locator('[data-state="paid"]')).toHaveCount(3)
  await expect(card.locator('[data-state="pending"]')).toHaveCount(3)
  await expect(card.getByTestId('installment-owner')).toHaveText(
    t('installments.plan.paidBy', { contact: PERSON }),
  )
  await expectFits(page, card)

  // Edit: a new name and 12 installments.
  await card.getByRole('button', { name: t('installments.plan.editLabel', { name: PLAN }) }).click()
  const edit = page.getByRole('dialog', { name: t('installments.edit.title') })
  await expect(edit).toBeVisible()
  await expect(edit.getByTestId('installment-plan-charges').getByRole('listitem')).toHaveCount(3)
  await edit.getByLabel(t('installments.form.name')).fill(RENAMED)
  await edit.getByLabel(t('installments.form.count')).fill('12')
  await edit.getByRole('button', { name: t('installments.edit.save') }).click()
  await expect(edit).toHaveCount(0)
  const renamed = page.getByTestId('installment-plan')
  await expect(renamed.getByRole('heading', { name: RENAMED })).toBeVisible()
  await expect(renamed.getByTestId('installment-summary')).toHaveText(
    summary(3, 12, 'US$ 1,350.00', LAST_MONTH_12),
  )

  // Delete it from the edit sheet (with a confirmation): Cuotas is empty, the rows untagged.
  await renamed
    .getByRole('button', { name: t('installments.plan.editLabel', { name: RENAMED }) })
    .click()
  const again = page.getByRole('dialog', { name: t('installments.edit.title') })
  await again
    .getByRole('button', { name: t('installments.plan.deleteLabel', { name: RENAMED }) })
    .click()
  await again.getByRole('button', { name: t('installments.plan.confirmButton') }).click()
  await expect(again).toHaveCount(0)
  await expect(page.getByText(t('installments.page.empty.title'))).toBeVisible()
  await page.goto(`/transactions?month=${MONTH}`)
  await expect(
    rows(page).filter({ hasText: MERCHANT }).getByTestId('installment-tag'),
  ).toHaveCount(0)
})

test('"New plan" starts from a picked charge', async ({ page }) => {
  await page.goto('/installments')
  await expect(page.getByText(t('installments.page.empty.title'))).toBeVisible()
  await page.getByRole('button', { name: t('installments.page.new') }).click()
  const picker = page.getByRole('dialog', { name: t('installments.picker.title') })
  await expect(picker).toBeVisible()
  // Newest first: February's store charge before January's and December's.
  await picker
    .getByTestId('installment-charges')
    .getByRole('button')
    .filter({ hasText: MERCHANT })
    .first()
    .click()

  const form = formSheet(page)
  await expect(form).toBeVisible()
  await expect(form.getByTestId('installment-position')).toHaveText(
    t('installments.form.position', { number: 3, count: '6' }),
  )
  // Unchecking December renumbers the rest: January is installment 1, February 2.
  await form.getByTestId('installment-earlier').getByRole('checkbox').first().uncheck()
  await expect(form.getByTestId('installment-position')).toHaveText(
    t('installments.form.position', { number: 2, count: '6' }),
  )
  await form.getByRole('button', { name: t('installments.form.submit') }).click()
  await expect(form).toHaveCount(0)

  const card = page.getByTestId('installment-plan')
  await expect(card).toHaveCount(1)
  await expect(card.locator('[data-state="paid"]')).toHaveCount(2)
  await expect(card.getByText(t('installments.plan.mine'), { exact: true })).toBeVisible()
})

test('the form asks which installment it is when the deduced one does not fit', async ({
  page,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await rows(page).filter({ hasText: MERCHANT }).click()
  const form = await openForm(page)
  await form.getByLabel(t('installments.form.count')).fill('2')
  await expect(form.getByTestId('installment-number-why')).toHaveText(
    t('installments.form.numberOver', { count: '2', number: 3 }),
  )
  await form.getByRole('button', { name: t('installments.form.submit') }).click()
  await expect(form.getByRole('alert')).toHaveText(
    t('installments.form.invalid.number', { count: 2 }),
  )
  await expect(form).toBeVisible()
})
