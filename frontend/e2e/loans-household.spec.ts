import { expect, test } from '@playwright/test'
import { t } from './text'

// Loans on the household server (tests/e2e_server.py --household: a made-up account pays
// "AUT PAGO 0000000088 REF n" four times, one of them an extra payment). «Deudas» creates the
// loan with its number; every payment links at once; the loan opens in Accounts as a liability
// with a negative balance, and a payment can be unlinked.
const WRITE = { 'X-Michelito': '1' }
const NAME = 'Home loan'

test.describe.configure({ mode: 'serial' })

// Every test starts and ends without loans (the server's database lives across specs).
async function removeLoans(request: import('@playwright/test').APIRequestContext) {
  const loans = (await (await request.get('/api/loans')).json()) as { id: number }[]
  for (const loan of loans) {
    expect((await request.delete(`/api/loans/${loan.id}`, { headers: WRITE })).ok()).toBe(true)
  }
}

test.beforeEach(async ({ request }) => removeLoans(request))
test.afterEach(async ({ request }) => removeLoans(request))

test('a loan made in Deudas links its payments and opens in Accounts', async ({ page }) => {
  await page.goto('/installments')
  await expect(page.getByRole('heading', { level: 1, name: t('loans.page.title') })).toBeVisible()
  await expect(page.getByText(t('loans.section.empty.title'))).toBeVisible()

  await page.getByRole('button', { name: t('loans.section.new') }).click()
  const form = page.getByTestId('loan-form')
  await form.getByLabel(t('loans.form.name')).fill(NAME)
  await form.getByLabel(t('loans.form.number')).fill('0000000088')
  await form.getByLabel(t('loans.form.principal')).fill('500,000')
  await form.getByLabel(t('loans.form.rate')).fill('12')
  await form.getByLabel(t('loans.form.term')).fill('60')
  await form.getByLabel(t('loans.form.start')).fill('2025-11-10')
  await form.getByRole('button', { name: t('loans.form.submit') }).click()

  const summary = page.getByTestId('loan-summary')
  await expect(summary).toContainText(NAME)
  await expect(summary).toContainText('−RD$')
  await summary.getByRole('link', { name: t('loans.list.openLabel', { name: NAME }) }).click()

  await expect(page).toHaveURL(/\/accounts\?account=loan-\d+$/)
  await expect(page.getByTestId('loan-account')).toHaveAttribute('aria-pressed', 'true')
  const card = page.getByTestId('loan-card')
  await expect(card.getByRole('heading', { name: NAME })).toBeVisible()
  await expect(card.getByTestId('loan-balance')).toContainText('−RD$')
  const payments = card.getByTestId('loan-payments').getByRole('listitem')
  await expect(payments).toHaveCount(4)

  await payments
    .first()
    .getByRole('button', { name: /no es de este préstamo/i }) // spanish-ui
    .click()
  await expect(payments).toHaveCount(3)
})
