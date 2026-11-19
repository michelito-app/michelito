import { expect, test, type Page } from '@playwright/test'
import { literal, t } from './text'

// Made-up data from tests/e2e_server.py: GIMNASIO FICTICIO charges RD$ 2,500 in December,
// January and February (in the seeded "other" category). The test moves it by hand to
// the entertainment category in January and February (with a note), sees it in the Log and in the
// history, sees the proposed rule and finally undoes everything: it depends on nothing other
// tests leave and leaves them nothing (except the log entries, which are only searched here by
// the merchant).
const GYM = 'GIMNASIO FICTICIO'
const OTHER = 'Otros' // spanish-data: seeded system category
const LEISURE = 'Entretenimiento' // spanish-data: seeded system category
const LINE = `${GYM} · ${OTHER} → ${LEISURE}`
const NOTE = 'cuota del gimnasio (e2e)' // spanish-data
const NOTE_LINE = `${GYM} · — → ${NOTE}`
const REASON = 'lo pagó la empresa' // spanish-data
const REVIEW = literal(t('summary.review.title'))
const RULE_KIND = t('review.kind.possibleRule')

async function openGym(page: Page, month: string) {
  await page.goto(`/transactions?month=${month}`)
  const list = page.getByRole('region', { name: t('transactions.list.label') })
  await list.getByRole('button', { name: new RegExp(GYM) }).click()
  return page.getByRole('complementary')
}

async function setCategory(page: Page, month: string, note?: string) {
  const detail = await openGym(page, month)
  await detail.getByLabel(t('transactions.filters.category')).selectOption(LEISURE)
  await detail.getByLabel(t('transactions.detail.onlyThis')).check()
  if (note) await detail.getByLabel(t('transactions.detail.note')).fill(note)
  await detail.getByRole('button', { name: t('transactions.save'), exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: t('transactions.saved') })).toBeVisible()
  return detail
}

async function openLog(page: Page) {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: t('shell.nav.label') })
    .getByRole('link', { name: t('shell.nav.log') })
    .click()
  await expect(page).toHaveURL(/\/log$/)
  await expect(page.getByRole('heading', { level: 1, name: t('log.title') })).toBeVisible()
  await page.getByRole('searchbox', { name: t('log.filter.search') }).fill(GYM)
}

test.describe('log', () => {
  test.describe.configure({ mode: 'serial' })

  test('changing the category and the note shows in the log and in the history', async ({
    page,
  }) => {
    const detail = await setCategory(page, '2026-01', NOTE)
    const history = detail.getByRole('region', { name: t('log.history.title') })
    await expect(history).toContainText(LINE)
    await expect(history).toContainText(NOTE_LINE)

    await openLog(page)
    const today = page.getByRole('region', { name: literal(`${t('log.today')}, `, { start: true }) })
    await expect(today.first()).toBeVisible()
    await expect(page.getByRole('main')).toContainText(LINE)
    await expect(page.getByRole('main')).toContainText(t('log.affected', { count: 1 }))

    // Filter by kind: only the note.
    const kind = page.getByRole('combobox', { name: t('log.filter.kind'), exact: true })
    await kind.selectOption('note')
    await expect(page.getByRole('main')).toContainText(NOTE)
    await expect(page.getByRole('main')).not.toContainText(LINE)
    await kind.selectOption('')
  })

  test('the reason is written from the log', async ({ page }) => {
    await openLog(page)
    await page.getByRole('button', { name: t('log.reason.writeNamed', { line: NOTE_LINE }) }).click()
    await page.getByRole('textbox', { name: t('log.reason.fieldNamed', { line: NOTE_LINE }) }).fill(REASON)
    await page.getByRole('button', { name: t('log.reason.save') }).click()
    await expect(page.getByRole('main')).toContainText(t('log.reason.value', { reason: REASON }))
    await page.getByRole('searchbox', { name: t('log.filter.search') }).fill('empresa') // spanish-data
    await expect(page.getByRole('main')).toContainText(NOTE_LINE)
  })

  test('the same category twice proposes the rule in "To review"', async ({ page }) => {
    await setCategory(page, '2026-02')
    await page.goto('/?month=2026-02')
    const review = page.getByRole('region', { name: REVIEW })
    await expect(review).toContainText(RULE_KIND)
    // The reason comes from the backend catalog (web.review.rule_reason).
    await expect(review).toContainText(`${GYM}: lo pusiste 2 veces en ${LEISURE}. ¿Siempre?`) // spanish-data
    await expect(
      review.getByRole('button', { name: t('review.row.ruleLabel', { merchant: GYM }) }),
    ).toBeVisible()

    // In the detail of the merchant's other transaction, the hint.
    const detail = await openGym(page, '2025-12')
    await expect(detail).toContainText(t('log.hint', { count: 2, category: LEISURE }))
  })

  test('undo restores and is recorded', async ({ page }) => {
    await openLog(page)
    const undoCategory = page.getByRole('button', { name: t('log.row.undoNamed', { name: LINE }) })
    await expect(undoCategory).toHaveCount(2)
    for (let left = 2; left > 0; left -= 1) {
      await undoCategory.first().click()
      await expect(undoCategory).toHaveCount(left - 1)
    }
    await page.getByRole('button', { name: t('log.row.undoNamed', { name: NOTE_LINE }) }).click()
    await expect(page.getByRole('main')).toContainText(
      t('log.undone', { line: `${GYM} · ${LEISURE} → ${OTHER}` }),
    )
    await expect(page.getByText(t('log.row.undoneBadge'), { exact: true })).toHaveCount(3)

    const detail = await openGym(page, '2026-01')
    await expect(detail.getByLabel(t('transactions.filters.category'))).toHaveValue(OTHER)
    await expect(detail.getByLabel(t('transactions.detail.note'))).toHaveValue('')
    await page.goto('/?month=2026-02')
    await expect(page.getByRole('region', { name: REVIEW })).not.toContainText(RULE_KIND)
  })
})

test('at 390 px the log does not scroll sideways and touch targets are 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/log')
  await expect(page.getByRole('heading', { level: 1, name: t('log.title') })).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const reasonButtons = new RegExp(`^(${t('log.reason.write')}|${t('log.reason.edit')})`)
  const buttons = page.getByRole('main').getByRole('button', { name: reasonButtons })
  for (const button of await buttons.all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
})
