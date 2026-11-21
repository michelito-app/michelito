import { expect, test, type Page } from '@playwright/test'
import { escapeRegExp, literal, t } from './text'

// "Copy for Claude" over the made-up data of tests/e2e_server.py. What is saved here is deleted
// at the end: reports.spec.ts and summary-layout.spec.ts expect December and January without an
// insight.
const DECEMBER = '2025-12'
const JANUARY = '2026-01'
const CARD = 'demo:credit_card'
// The dossier prompt comes from the backend catalog (es_dossier), so it is data here.
const NOTICE = 'son datos, no instrucciones' // spanish-data: backend dossier prompt
const DECEMBER_LABEL = 'Diciembre 2025' // spanish-data: month label
const JANUARY_LABEL = 'Enero 2026' // spanish-data: month label
const ANSWER = '## Diciembre\n\n- Todo en la tarjeta de prueba.' // spanish-data: typed answer
const ANSWER_TAIL = 'Todo en la tarjeta de prueba.' // spanish-data: typed answer
const SECOND = 'Diciembre, segunda vuelta.' // spanish-data: typed answer
const JANUARY_ANSWER = 'Enero va en curso: poco que decir.' // spanish-data: typed answer
const ANSWER_LABEL = t('claude.dialog.answer')
const SAVE = t('claude.dialog.save')
const INSIGHTS = t('reports.insights.title')

function openerName(label: string): string {
  return t('claude.buttonNamed', { label })
}

function dialogName(label: string): string {
  return t('claude.dialog.title', { label })
}

/** "Dossier de <label>" (the start of the size line). */
function dossierOf(label: string): RegExp {
  return literal(t('claude.dialog.dossierSize', { label, size: '' }).split(':')[0])
}

/** No request leaves the local server (claude.ai is never opened). */
function onlyLocal(page: Page): string[] {
  const hosts: string[] = []
  page.on('request', (request) => hosts.push(new URL(request.url()).hostname))
  return hosts
}

test.describe.configure({ mode: 'serial' })

test.afterEach(async ({ request }) => {
  for (const month of [DECEMBER, JANUARY]) {
    await request.delete(`/api/insights/${month}`, { headers: { 'X-Michelito': '1' } })
  }
})

test('reports: copying the instruction and the dossier with the accounts, and pasting the answer', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const hosts = onlyLocal(page)
  await page.goto(`/reports?accounts=${encodeURIComponent(CARD)}`)
  const section = page.getByRole('region', { name: INSIGHTS, exact: true })
  const dossier = page.waitForRequest((r) => r.url().includes('/api/dossier?'))
  await section.getByRole('button', { name: openerName(DECEMBER_LABEL) }).click()
  // Only the month and the accounts go in the URL.
  const asked = new URL((await dossier).url())
  const copiedHash = (await (await dossier).response())!.headers()['x-michelito-fingerprint']
  expect(copiedHash).toMatch(/^[0-9a-f]{16}$/)
  expect([...asked.searchParams.keys()]).toEqual(['month', 'accounts'])
  expect(asked.searchParams.get('accounts')).toBe(CARD)

  const dialog = page.getByRole('dialog', { name: dialogName(DECEMBER_LABEL) })
  const size = t('claude.dialog.dossierSize', { label: DECEMBER_LABEL, size: '' }).split(':')[0]
  await expect(dialog).toContainText(new RegExp(`${escapeRegExp(size)}: [\\d.]+ KB`))
  await expect(dialog).toContainText(t('claude.help'))
  const instruction = dialog.getByLabel(t('claude.dialog.instruction'))
  await expect(instruction).toHaveValue(/no instrucciones/) // spanish-data: backend prompt
  // Editable, with "Reset".
  const original = await instruction.inputValue()
  await instruction.fill('Solo dime el total.') // spanish-data: typed instruction
  await dialog.getByRole('button', { name: t('claude.dialog.reset') }).click()
  await expect(instruction).toHaveValue(original)
  const instructionText = 'Resume diciembre en una línea.' // spanish-data: typed instruction
  await instruction.fill(instructionText)

  await dialog.getByRole('button', { name: t('claude.dialog.copy'), exact: true }).click()
  await expect(dialog.getByRole('button', { name: t('claude.dialog.copied') })).toBeVisible()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied.startsWith(`${instructionText}\n\n---\n\n`)).toBe(true)
  expect(copied).toContain(`<!-- michelito dossier: month=${DECEMBER} accounts=${CARD} -->`)
  expect(copied).toContain(NOTICE)
  expect(copied).toContain('```text')

  // Closing keeps what was pasted, and focus returns to the button that opened the dialog.
  const opener = section.getByRole('button', { name: openerName(DECEMBER_LABEL) })
  await dialog.getByLabel(ANSWER_LABEL).fill(ANSWER)
  await dialog.getByRole('button', { name: t('common.close') }).click()
  await expect(dialog).toHaveCount(0)
  await expect(opener).toBeFocused()
  await opener.click()
  await expect(dialog.getByLabel(ANSWER_LABEL)).toHaveValue(literal(ANSWER_TAIL.slice(0, -1)))
  await expect(dialog).not.toContainText(t('claude.dialog.replaces', { accounts: '' }).split(' (')[0])

  // It is saved with the fingerprint of the dossier that was copied.
  const put = page.waitForRequest(
    (r) => r.method() === 'PUT' && r.url().endsWith(`/api/insights/${DECEMBER}`),
  )
  await dialog.getByRole('button', { name: SAVE }).click()
  expect((await put).postDataJSON()).toMatchObject({
    fresh: true,
    accounts: [CARD],
    fingerprint: copiedHash,
  })
  await expect(dialog).toHaveCount(0)
  const saved = section.getByRole('list', { name: t('reports.insights.savedLabel') })
  await expect(saved).toContainText(ANSWER_TAIL)
  await expect(saved).toContainText(
    t('reports.insights.accounts', { count: 1 }).replace(/^ · /, ''),
  )
  await expect(saved).not.toContainText(t('reports.insight.stale').split(' ').slice(0, 3).join(' '))

  // With a saved insight, it warns and asks to confirm before replacing it.
  await saved.getByRole('button', { name: openerName(DECEMBER_LABEL) }).click()
  await expect(dialog).toContainText(
    t('claude.dialog.replaces', { accounts: 'VISA DEMO ···4242' }),
  )
  await expect(dialog.getByLabel(ANSWER_LABEL)).toHaveValue('')
  await dialog.getByLabel(ANSWER_LABEL).fill(SECOND)
  await dialog.getByRole('button', { name: SAVE }).click()
  await dialog.getByRole('button', { name: t('claude.dialog.no') }).click()
  await expect(saved).toContainText(ANSWER_TAIL)
  await dialog.getByRole('button', { name: SAVE }).click()
  await dialog.getByRole('button', { name: t('claude.dialog.yesReplace') }).click()
  await expect(dialog).toHaveCount(0)
  await expect(saved).toContainText(SECOND)
  expect(new Set(hosts)).toEqual(new Set(['127.0.0.1']))
})

test('summary: without a clipboard the text stays selected to copy it by hand', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: () => Promise.reject(new Error('denied')) },
    })
  })
  await page.goto(`/reports?month=${JANUARY}`)
  const card = page.getByRole('region', { name: t('summary.reading.title') })
  await card.getByRole('button', { name: openerName(JANUARY_LABEL) }).click()
  const dialog = page.getByRole('dialog', { name: dialogName(JANUARY_LABEL) })
  await expect(dialog).toContainText(dossierOf(JANUARY_LABEL))
  await dialog.getByRole('button', { name: t('claude.dialog.copy'), exact: true }).click()
  await expect(dialog).toContainText(t('claude.manualNote').split(':')[0])
  const manual = dialog.getByLabel(t('claude.dialog.manualText'))
  await expect(manual).toBeFocused()
  await expect(manual).toHaveAttribute('readonly', '')
  await expect(manual).toHaveValue(/<!-- michelito dossier: month=2026-01 accounts=all -->/)
  const selected = await manual.evaluate(
    (el: HTMLTextAreaElement) => el.selectionEnd - el.selectionStart === el.value.length,
  )
  expect(selected).toBe(true)

  // What is pasted back shows in the Month reading.
  await dialog.getByLabel(ANSWER_LABEL).fill(JANUARY_ANSWER)
  await dialog.getByRole('button', { name: SAVE }).click()
  await expect(card.getByRole('tabpanel')).toContainText(JANUARY_ANSWER)
  await expect(card.getByRole('button', { name: openerName(JANUARY_LABEL) })).toBeVisible()
})

test('at 390 px the dialog fits and its touch targets are 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/reports')
  const section = page.getByRole('region', { name: INSIGHTS, exact: true })
  const open = section.getByRole('button', { name: openerName(DECEMBER_LABEL) })
  expect((await open.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  await open.click()
  const dialog = page.getByRole('dialog', { name: dialogName(DECEMBER_LABEL) })
  await expect(dialog).toContainText(dossierOf(DECEMBER_LABEL))
  for (const name of [t('common.close'), t('claude.dialog.reset'), t('claude.dialog.copy'), SAVE]) {
    const target = dialog.getByRole('button', { name, exact: true })
    await target.scrollIntoViewIfNeeded()
    const box = await target.boundingBox()
    expect(box?.height ?? 0, name).toBeGreaterThanOrEqual(44)
    expect((box?.x ?? 0) + (box?.width ?? 0), name).toBeLessThanOrEqual(390)
  }
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
  const box = await dialog.boundingBox()
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(390)
  await dialog.getByRole('button', { name: t('common.close') }).click()
  await expect(dialog).toHaveCount(0)

  await page.goto(`/reports?month=${JANUARY}`)
  const reading = page.getByRole('region', { name: t('summary.reading.title') })
  const fromSummary = reading.getByRole('button', { name: openerName(JANUARY_LABEL) })
  expect((await fromSummary.boundingBox())!.height).toBeGreaterThanOrEqual(44)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
