import { expect, test } from '@playwright/test'

// Datos inventados de tests/e2e_server.py: diciembre 2025 completo; enero y febrero en curso.
// Este archivo corre después de board.spec.ts con la misma base: no depende de lo que se marcó
// allí (solo lee o deshace lo que marca).

test('reportes: el menú lleva a la tabla de meses', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name: 'Reportes' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Reportes' })).toBeVisible()
  const table = page.getByRole('region', { name: 'Comparar meses' })
  await expect(table.getByRole('columnheader')).toContainText(['Fila', 'Diciembre 25', /Enero 26/, /Febrero 26/])
  const rows = table.getByRole('rowheader')
  await expect(rows.nth(0)).toHaveText('Ingresos')
  await expect(rows.nth(1)).toHaveText('Gastos')
  await expect(rows.nth(2)).toHaveText('Transferencias a terceros')
  await expect(rows.nth(3)).toHaveText('Te quedó')
  await expect(table.getByRole('row', { name: /^Gastos/ })).toContainText('19,883')
})

test('reportes: una celda abre Transacciones con el mes, la categoría y las cuentas', async ({ page }) => {
  await page.goto('/reportes?cuentas=demo%3Acredit_card')
  const table = page.getByRole('region', { name: 'Comparar meses' })
  await table.getByRole('link', { name: /^Viajes, Febrero 2026: RD\$ 45,000/ }).click()
  await expect(page).toHaveURL(/\/transacciones\?mes=2026-02&categoria=Viajes&cuentas=demo%3Acredit_card/)
  await expect(page.getByRole('heading', { level: 1, name: 'Transacciones' })).toBeVisible()
})

test('reportes: el rango se elige con «Desde» y «Hasta»', async ({ page }) => {
  await page.goto('/reportes')
  const table = page.getByRole('region', { name: 'Comparar meses' })
  await table.getByLabel('Desde').selectOption('2026-01')
  await expect(page).toHaveURL(/desde=2026-01/)
  await expect(table.getByRole('columnheader', { name: /Diciembre/ })).toHaveCount(0)
  await expect(table.getByRole('columnheader', { name: /Enero 26/ })).toBeVisible()
})

test('reportes: el historial de «Para revisar» filtra por tipo y deja volver a revisar', async ({
  page,
}) => {
  await page.goto('/reportes')
  const history = page.getByRole('region', { name: 'Para revisar: historial' })
  await expect(history).toContainText('STREAMING FICTICIO')
  await history.getByRole('button', { name: 'Transferencia grande', exact: true }).click()
  await expect(history.getByRole('button', { name: 'Transferencia grande', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(history).not.toContainText('STREAMING FICTICIO')

  // Solo las subidas de precio; el streaming puede venir revisado o no: se cambia y se deshace.
  await history.getByRole('button', { name: 'Subió de precio', exact: true }).click()
  const undo = history.getByRole('button', { name: 'Volver a revisar: STREAMING FICTICIO' })
  const done = history.getByRole('button', { name: 'Ya lo revisé: STREAMING FICTICIO' })
  await expect(undo.or(done)).toBeVisible()
  const wasReviewed = await undo.isVisible()
  await (wasReviewed ? undo : done).click()
  await expect(wasReviewed ? done : undo).toBeVisible()
  await (wasReviewed ? done : undo).click()
  await expect(wasReviewed ? undo : done).toBeVisible()
})

test('reportes: en 390 px la tabla se desplaza dentro de su caja, no la página', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/reportes')
  const scroller = page.getByRole('region', { name: 'Comparar meses' }).getByLabel(/Tabla de meses/)
  await expect(scroller).toBeVisible()
  const page_width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(page_width).toBeLessThanOrEqual(390)
  const overflow = await scroller.evaluate((el) => el.scrollWidth > el.clientWidth)
  expect(overflow).toBe(true)
})

test.describe('análisis guardados', () => {
  test.describe.configure({ mode: 'serial' })
  const DECEMBER = '2025-12'

  test('reportes: un mes sin análisis ofrece copiar el comando', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto('/reportes')
    const section = page.getByRole('region', { name: 'Análisis', exact: true })
    await expect(section).toContainText('finanzas analisis 2025-12')
    const copy = section.getByRole('button', { name: 'Copiar comando para analizar Diciembre 2025' })
    await copy.click()
    await expect(copy).toHaveText('Copiado')
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('finanzas analisis 2025-12')
  })

  test('resumen: el análisis guardado sale en la pestaña Análisis de «Lectura del mes»', async ({
    page,
    request,
  }) => {
    // Como `finanzas insight guardar`: lo guarda la API con la huella de los datos de hoy.
    const saved = await request.put(`/api/insights/${DECEMBER}`, {
      headers: { 'X-Finanzas': '1' },
      data: { text: 'Diciembre: la ferretería explica casi todo el gasto.' },
    })
    expect(saved.ok()).toBe(true)
    await page.goto(`/?mes=${DECEMBER}`)
    const card = page.getByRole('region', { name: 'Lectura del mes' })
    await expect(card.getByRole('tab', { name: 'Análisis' })).toHaveAttribute('aria-selected', 'true')
    await expect(card.getByRole('tabpanel')).toContainText('Diciembre: la ferretería explica casi todo el gasto.')
    await expect(card).not.toContainText('Los datos cambiaron')
    await page.goto('/?mes=2026-01')
    await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Análisis' })).toHaveCount(0)
  })

  test('reportes: se edita y se borra', async ({ page }) => {
    await page.goto('/reportes')
    const section = page.getByRole('region', { name: 'Análisis', exact: true })
    const saved = section.getByRole('list', { name: 'Análisis guardados' })
    await expect(saved).toContainText('Diciembre 2025')
    await expect(section).not.toContainText('finanzas analisis 2025-12')
    await saved.getByRole('button', { name: 'Editar el análisis de Diciembre 2025' }).click()
    await saved.getByLabel('Análisis de Diciembre 2025 (Markdown)').fill('Diciembre corregido.')
    await saved.getByRole('button', { name: 'Guardar' }).click()
    await expect(saved).toContainText('Diciembre corregido.')

    await saved.getByRole('button', { name: 'Borrar el análisis de Diciembre 2025' }).click()
    await saved.getByRole('button', { name: 'Sí, borrar' }).click()
    await expect(section).toContainText('finanzas analisis 2025-12')
    await expect(section.getByRole('list', { name: 'Análisis guardados' })).toHaveCount(0)
  })
})
