import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py: GIMNASIO FICTICIO cobra RD$ 2,500 en diciembre, enero y
// febrero (en «Otros»). La prueba lo pasa a mano a «Entretenimiento» en enero y febrero (con una
// nota), lo ve en la Bitácora y en el historial, ve la regla propuesta y al final deshace todo:
// no depende de lo que dejen otras pruebas ni les deja nada (salvo las entradas de la bitácora,
// que solo se buscan aquí por el comercio).
const GYM = 'GIMNASIO FICTICIO'
const LINE = `${GYM} · Otros → Entretenimiento`
const NOTE = 'cuota del gimnasio (e2e)'

async function openGym(page: Page, month: string) {
  await page.goto(`/transacciones?mes=${month}`)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await list.getByRole('button', { name: new RegExp(GYM) }).click()
  return page.getByRole('complementary')
}

async function setCategory(page: Page, month: string, note?: string) {
  const detail = await openGym(page, month)
  await detail.getByLabel('Categoría').selectOption('Entretenimiento')
  await detail.getByLabel('Solo esta transacción').check()
  if (note) await detail.getByLabel('Nota').fill(note)
  await detail.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Guardado' })).toBeVisible()
  return detail
}

async function openLog(page: Page) {
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name: 'Bitácora' }).click()
  await expect(page).toHaveURL(/\/bitacora$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Bitácora' })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Buscar en la bitácora' }).fill(GYM)
}

test.describe('bitácora', () => {
  test.describe.configure({ mode: 'serial' })

  test('cambiar categoría y nota queda en la bitácora y en el historial', async ({ page }) => {
    const detail = await setCategory(page, '2026-01', NOTE)
    const history = detail.getByRole('region', { name: 'Historial' })
    await expect(history).toContainText(LINE)
    await expect(history).toContainText(`${GYM} · — → ${NOTE}`)

    await openLog(page)
    const today = page.getByRole('region', { name: /^Hoy, / })
    await expect(today.first()).toBeVisible()
    await expect(page.getByRole('main')).toContainText(LINE)
    await expect(page.getByRole('main')).toContainText('1 transacción')

    // Filtro por tipo: solo la nota.
    await page.getByRole('combobox', { name: 'Tipo de cambio', exact: true }).selectOption('nota')
    await expect(page.getByRole('main')).toContainText(NOTE)
    await expect(page.getByRole('main')).not.toContainText(LINE)
    await page.getByRole('combobox', { name: 'Tipo de cambio', exact: true }).selectOption('')
  })

  test('el motivo se escribe desde la bitácora', async ({ page }) => {
    await openLog(page)
    const noteLine = `${GYM} · — → ${NOTE}`
    await page.getByRole('button', { name: `Escribir motivo: ${noteLine}` }).click()
    await page.getByRole('textbox', { name: `Motivo: ${noteLine}` }).fill('lo pagó la empresa')
    await page.getByRole('button', { name: 'Guardar motivo' }).click()
    await expect(page.getByRole('main')).toContainText('Motivo: lo pagó la empresa')
    await page.getByRole('searchbox', { name: 'Buscar en la bitácora' }).fill('empresa')
    await expect(page.getByRole('main')).toContainText(noteLine)
  })

  test('dos veces la misma categoría propone la regla en «Para revisar»', async ({ page }) => {
    await setCategory(page, '2026-02')
    await page.goto('/?mes=2026-02')
    const review = page.getByRole('region', { name: /Para revisar/ })
    await expect(review).toContainText('¿Regla para el comercio?')
    await expect(review).toContainText(`${GYM}: lo pusiste 2 veces en Entretenimiento. ¿Siempre?`)
    await expect(review.getByRole('button', { name: `Crear regla: ${GYM}` })).toBeVisible()

    // En el detalle de la otra transacción del comercio, la pista.
    const detail = await openGym(page, '2025-12')
    await expect(detail).toContainText('Las otras 2 veces lo pusiste en Entretenimiento.')
  })

  test('deshacer restaura y queda registrado', async ({ page }) => {
    await openLog(page)
    const undoCategory = page.getByRole('button', { name: `Deshacer: ${LINE}` })
    await expect(undoCategory).toHaveCount(2)
    for (let left = 2; left > 0; left -= 1) {
      await undoCategory.first().click()
      await expect(undoCategory).toHaveCount(left - 1)
    }
    await page.getByRole('button', { name: `Deshacer: ${GYM} · — → ${NOTE}` }).click()
    await expect(page.getByRole('main')).toContainText(`Deshecho: ${GYM} · Entretenimiento → Otros`)
    await expect(page.getByText('Deshecha', { exact: true })).toHaveCount(3)

    const detail = await openGym(page, '2026-01')
    await expect(detail.getByLabel('Categoría')).toHaveValue('Otros')
    await expect(detail.getByLabel('Nota')).toHaveValue('')
    await page.goto('/?mes=2026-02')
    await expect(page.getByRole('region', { name: /Para revisar/ })).not.toContainText('¿Regla para el comercio?')
  })
})

test('a 390 px la bitácora no se desplaza a lo ancho y los toques miden 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/bitacora')
  await expect(page.getByRole('heading', { level: 1, name: 'Bitácora' })).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const buttons = page.getByRole('main').getByRole('button', { name: /^(Escribir|Editar) motivo/ })
  for (const button of await buttons.all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
})
