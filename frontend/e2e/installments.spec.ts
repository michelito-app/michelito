import { expect, test, type Locator, type Page } from '@playwright/test'
import { t } from './text'

// Installment plans on their own server (tests/e2e_server.py --installments: a made-up US$ 150
// store charge on the VISA DEMO in December, January and February). From February's charge, "It is an installment…" finds the two
// earlier ones (it is installment 3); the rows say "cuota n/6"; Recurring shows the plan's card;
// deleting it leaves the rows as they were. Desktop and an iPhone's size (WebKit).
const MONTH = '2026-02'
const MERCHANT = 'TIENDA COM'
const PLAN = 'Phone (Store)'
const WRITE = { 'X-Michelito': '1' }
const LAST_MONTH = 'mayo 2026' // spanish-ui (December + 5 months)

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

/** Opens "It is an installment…" from the open detail: a button of its section on a wide
 * screen, a row of "More actions" on a phone. */
async function openForm(page: Page): Promise<Locator> {
  const panel = detail(page)
  if (isPhone(page)) {
    await panel.getByRole('button', { name: t('installments.detail.title') }).click()
  } else {
    await panel.getByRole('button', { name: t('installments.detail.create') }).click()
  }
  const form = page.getByRole('dialog', { name: t('installments.form.title') })
  await expect(form).toBeVisible()
  return form
}

test('a plan made from a charge tags its rows, shows in Recurring and can be deleted', async ({
  page,
}) => {
  await page.goto(`/transactions?month=${MONTH}`)
  const row = rows(page).filter({ hasText: MERCHANT })
  await expect(row).toHaveCount(1)
  await expect(row.getByTestId('installment-tag')).toHaveCount(0)
  await row.click()

  const form = await openForm(page)
  await expect(form.getByTestId('installment-found')).toHaveText(
    t('installments.form.found', { count: 2 }),
  )
  await expect(form.getByLabel(t('installments.form.number'))).toHaveValue('3')
  await expect(form.getByLabel(t('installments.form.count'))).toHaveValue('6')
  await expect(form.getByRole('radio', { name: new RegExp(t('installments.form.mine')) })).toBeChecked()
  await form.getByLabel(t('installments.form.name')).fill(PLAN)
  await form.getByRole('button', { name: t('installments.form.submit') }).click()
  await expect(form).toHaveCount(0)

  const linked = t('installments.detail.linked', { number: 3, count: 6, name: PLAN })
  const panel = detail(page)
  if (isPhone(page)) {
    await expect(panel.getByTestId('mobile-link-installment')).toContainText(linked)
  } else {
    await expect(panel.getByTestId('installment-linked')).toHaveText(linked)
  }

  // The rows: February is installment 3, January (found before it) installment 2.
  const tag = (number: number) => t('installments.row.tag', { number, count: 6, name: PLAN })
  await page.goto(`/transactions?month=${MONTH}`)
  await expect(rows(page).filter({ hasText: MERCHANT }).getByTestId('installment-tag')).toHaveText(
    tag(3),
  )
  await page.goto('/transactions?month=2026-01')
  await expect(rows(page).filter({ hasText: MERCHANT }).getByTestId('installment-tag')).toHaveText(
    tag(2),
  )

  // Recurring: the plan's card with what is left and each installment's state.
  await page.goto('/recurring')
  const plans = page.getByTestId('installment-plans')
  await expect(plans.getByRole('heading', { name: t('installments.plans.title') })).toBeVisible()
  const card = plans.getByTestId('installment-plan')
  await expect(card).toHaveCount(1)
  await expect(card.getByRole('heading', { name: PLAN })).toBeVisible()
  await expect(card.getByTestId('installment-summary')).toHaveText(
    t('installments.plan.summary', {
      paid: 3,
      count: 6,
      amount: 'US$ 450.00',
      month: LAST_MONTH,
    }),
  )
  await expect(card.locator('[data-state="paid"]')).toHaveCount(3)
  await expect(card.locator('[data-state="pending"]')).toHaveCount(3)
  const size = await card.boundingBox()
  expect(size).not.toBeNull()
  expect(size!.x + size!.width).toBeLessThanOrEqual(page.viewportSize()!.width)

  // Delete it (with a confirmation): the card leaves and the rows lose their tag.
  await card.getByRole('button', { name: t('installments.plan.deleteLabel', { name: PLAN }) }).click()
  await card.getByRole('button', { name: t('installments.plan.confirmButton') }).click()
  await expect(plans).toHaveCount(0)
  await page.goto(`/transactions?month=${MONTH}`)
  await expect(rows(page).filter({ hasText: MERCHANT })).toHaveCount(1)
  await expect(rows(page).filter({ hasText: MERCHANT }).getByTestId('installment-tag')).toHaveCount(0)
})

test('the form says what is wrong instead of saving an impossible plan', async ({ page }) => {
  await page.goto(`/transactions?month=${MONTH}`)
  await rows(page).filter({ hasText: MERCHANT }).click()
  const form = await openForm(page)
  await form.getByLabel(t('installments.form.count')).fill('2')
  await form.getByRole('button', { name: t('installments.form.submit') }).click()
  await expect(form.getByRole('alert')).toHaveText(t('installments.form.invalid.number', { count: 2 }))
  await expect(form).toBeVisible()
})
