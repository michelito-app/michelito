// Helpers for the specs that also check the phone width (390 px): there some controls live
// behind a sheet or a closed section, so the same steps take one more tap.
import { expect, type Page } from '@playwright/test'
import { escapeRegExp, t } from './text'

/** The Summary's collapsible sections (phone) start open on the next page loads. */
export async function openSummarySections(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        'michelito.summary.openSections',
        JSON.stringify(['reading', 'upcoming', 'categories', 'trend', 'details']),
      )
    } catch {
      // No storage: the sections stay closed and the spec says so when it fails.
    }
  })
}

/** Picks an option of a Transactions filter (kind, category, grouping, sort): in the search row
 * on a wide screen, in the «Filters» sheet on a phone (closed afterwards). */
export async function chooseFilter(page: Page, label: string, option: string): Promise<void> {
  const search = page.getByRole('search')
  await expect(search.getByRole('searchbox')).toBeVisible()
  const inline = search.getByRole('combobox', { name: label, exact: true })
  if ((await inline.count()) > 0) {
    await inline.selectOption(option)
    return
  }
  await search
    .getByRole('button', { name: new RegExp(`^${escapeRegExp(t('transactions.filters.title'))}`) })
    .click()
  const sheet = page.getByRole('dialog', { name: t('transactions.filters.title') })
  await sheet.getByRole('combobox', { name: label, exact: true }).selectOption(option)
  await sheet.getByRole('button', { name: t('transactions.filters.done') }).click()
  await expect(sheet).toHaveCount(0)
}

/** The fingerprint of a Transactions row. */
export async function rowFingerprint(page: Page, name: RegExp): Promise<string> {
  const row = page
    .getByRole('region', { name: t('common.transactionListLabel') })
    .getByRole('button', { name })
  const fingerprint = await row.getAttribute('data-fingerprint')
  expect(fingerprint).toBeTruthy()
  return fingerprint!
}
