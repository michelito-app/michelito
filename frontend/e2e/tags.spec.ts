import { expect, test } from '@playwright/test'
import { t } from './text'

// Made-up data from tests/e2e_server.py: the closed group "Ropa de Marta" (RD$ 4,350 split in
// two) has its own tag, which counts only the user's share; the extra card has
// GASOLINERA FICTICIA SANTIAGO (RD$ 2,400, 28 Jan) and TALLER FICTICIO MECANICA (RD$ 1,500,
// 4 Feb). The test creates a tag, adds those two through "Add transactions", checks the
// total, removes one and deletes the tag: it leaves the data as it found it.
const GROUP = 'Ropa de Marta' // spanish-data
const TAG = 'Amueblar (e2e)' // spanish-data
const FUEL = 'GASOLINERA FICTICIA SANTIAGO'
const GARAGE = 'TALLER FICTICIO MECANICA'

test('a tag gathers transactions across months and adds up what was spent', async ({ page }) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: t('shell.nav.label') })
    .getByRole('link', { name: t('tags.nav') })
    .click()
  await expect(page).toHaveURL(/\/tags$/)

  const group = page.getByRole('link', { name: t('tags.list.open', { name: GROUP }) })
  await expect(group).toContainText(t('tags.summary.spent', { amount: 'RD$ 2,175' }))

  await page.getByRole('textbox', { name: t('tags.new.label') }).fill(TAG)
  await page.getByRole('button', { name: t('tags.new.create') }).click()
  await expect(page.getByRole('heading', { level: 1, name: TAG })).toBeVisible()
  await expect(page.getByText(t('tags.detail.empty'))).toBeVisible()

  await page.getByRole('button', { name: t('tags.action.add') }).click()
  await page.getByLabel(t('tags.picker.from')).fill('2026-01-28')
  await page.getByLabel(t('tags.picker.to')).fill('2026-02-04')
  await page.getByRole('checkbox', { name: FUEL }).click()
  await page.getByRole('checkbox', { name: GARAGE }).click()
  await page
    .getByRole('button', { name: t('tags.picker.submit', { count: 2, amount: 'RD$ 3,900' }) })
    .click()

  const members = page.getByRole('region', { name: t('tags.detail.members') })
  await expect(members.getByText(FUEL)).toBeVisible()
  await expect(members.getByText(GARAGE)).toBeVisible()
  await expect(page.getByText(t('tags.summary.spent', { amount: 'RD$ 3,900' }))).toBeVisible()

  await members.getByRole('button', { name: t('tags.detail.removeLabel', { name: GARAGE }) }).click()
  await expect(page.getByText(t('tags.summary.spent', { amount: 'RD$ 2,400' }))).toBeVisible()

  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: t('tags.action.delete') }).click()
  await expect(page).toHaveURL(/\/tags$/)
  await expect(page.getByRole('link', { name: t('tags.list.open', { name: TAG }) })).toHaveCount(0)
})
