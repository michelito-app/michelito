import { expect, test, type Page } from '@playwright/test'

// Servidor `--hogar` de tests/e2e_server.py (datos inventados): la «Cuenta P2P» con tres créditos
// de terceros distintos por vender cripto (todos con «P2P» en la descripción, RD$ 40,500 en
// enero) que caen en «Otros ingresos». Cada prueba deshace en la Bitácora lo que hizo.
const MONTH = '2026-01'
const LINE = '3 transacciones · Otros ingresos → Cripto'
const REASON = 'Venta de USDT por P2P'

async function filterCrypto(page: Page) {
  await page.goto(`/transacciones?mes=${MONTH}`)
  const search = page.getByRole('search')
  await search.getByRole('combobox', { name: 'Tipo', exact: true }).selectOption('Ingresos')
  await search
    .getByRole('combobox', { name: 'Categoría', exact: true })
    .selectOption('Otros ingresos')
  await search.getByRole('searchbox').fill('P2P')
  await expect(page).toHaveURL(/q=P2P/)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button')).toHaveCount(3)
  return list
}

async function undoBatch(page: Page) {
  await page.goto('/bitacora')
  await page.getByRole('searchbox', { name: 'Buscar en la bitácora' }).fill('Cripto')
  await page.getByRole('button', { name: `Deshacer: ${LINE}`, exact: true }).click()
  await expect(page.getByRole('main')).toContainText(
    'Deshecho: 3 transacciones · Cripto → Otros ingresos',
  )
}

test('filtrar, seleccionar varias, pasar a Cripto con motivo y deshacer en la Bitácora', async ({
  page,
}) => {
  const list = await filterCrypto(page)
  await page.getByRole('button', { name: 'Seleccionar', exact: true }).click()
  const bar = page.getByRole('region', { name: 'Acciones de la selección' })
  await expect(bar).toContainText('0 seleccionadas · RD$ 0')
  // El foco va a la primera casilla; cada una dice el día.
  await expect(list.getByRole('checkbox').first()).toBeFocused()

  await list.getByRole('checkbox', { name: /^Seleccionar 8 ene MB DESDE/ }).check()
  await list.getByRole('checkbox', { name: /^Seleccionar 16 ene TRANSFERENCIA RECIBIDA/ }).check()
  await expect(bar).toContainText('2 seleccionadas · RD$ 20,500')
  await bar.getByRole('button', { name: 'Seleccionar todo lo visible (3)' }).click()
  await expect(bar).toContainText('3 seleccionadas · RD$ 40,500')
  await expect(list.getByRole('checkbox', { checked: true })).toHaveCount(3)

  await bar.getByRole('combobox', { name: 'Nueva categoría', exact: true }).selectOption('Cripto')
  const reason = bar.getByRole('textbox', { name: 'Motivo (opcional)', exact: true })
  await reason.fill(REASON)
  await reason.press('Escape') // Esc en un campo de la barra no sale del modo
  await expect(bar).toContainText('3 seleccionadas')
  await bar.getByRole('button', { name: 'Cambiar categoría', exact: true }).click()
  const notice = page.getByRole('status').filter({ hasText: 'pasaron a Cripto' })
  await expect(notice).toContainText('3 pasaron a Cripto')
  await expect(notice).toBeFocused()
  await expect(notice.getByRole('link', { name: 'Ver en la Bitácora' })).toBeVisible()
  await expect(bar).toHaveCount(0)
  // Ya no son «Otros ingresos»: con el mismo filtro la lista queda vacía.
  await expect(page.getByRole('main')).toContainText('Ninguna transacción con estos filtros')

  // El Resumen y Reportes los muestran como un ingreso propio.
  await page.goto(`/?mes=${MONTH}`)
  await expect(page.getByTestId('income-lines')).toContainText('Cripto RD$ 40,500')
  await page.goto('/reportes')
  await expect(page.getByRole('row', { name: /^Cripto/ })).toContainText('40,500')

  await page.getByRole('link', { name: 'Bitácora' }).first().click()
  await page.getByRole('searchbox', { name: 'Buscar en la bitácora' }).fill('Cripto')
  await expect(page.getByRole('main')).toContainText(LINE)
  await expect(page.getByRole('main')).toContainText(`Motivo: ${REASON}`)
  await undoBatch(page)

  const back = await filterCrypto(page)
  await expect(back.getByRole('button', { name: /P2P/ })).toHaveCount(3)
})

test('en 390 px la barra queda abajo sin tapar la lista ni desbordar; Esc sale', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const list = await filterCrypto(page)
  await page.getByRole('button', { name: 'Seleccionar', exact: true }).click()
  const bar = page.getByRole('region', { name: 'Acciones de la selección' })
  await bar.getByRole('button', { name: 'Seleccionar todo lo visible (3)' }).click()
  await expect(bar).toContainText('3 seleccionadas · RD$ 40,500')

  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  expect(widths.scroll).toBeLessThanOrEqual(widths.client)
  const box = await bar.boundingBox()
  expect(box && box.y + box.height).toBeCloseTo(844, 0)
  // Al final de la página la última fila queda por encima de la barra.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  const last = list.getByRole('checkbox').last()
  const row = await last.boundingBox()
  const barTop = (await bar.boundingBox())!.y
  expect(row!.y + row!.height).toBeLessThanOrEqual(barTop)
  const checkbox = await list.locator('label').first().boundingBox()
  expect(checkbox!.height).toBeGreaterThanOrEqual(44)

  await page.keyboard.press('Escape')
  await expect(bar).toHaveCount(0)
  await expect(list.getByRole('button')).toHaveCount(3)
})

test('con grupos, «Seleccionar todo lo visible» marca solo los grupos abiertos', async ({
  page,
}) => {
  await page.goto(`/transacciones?mes=${MONTH}&tipo=ingresos&agrupar=categoria`)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await page.getByRole('button', { name: 'Seleccionar', exact: true }).click()
  const bar = page.getByRole('region', { name: 'Acciones de la selección' })
  // Todo plegado: no se ve ninguna fila, no hay nada que «seleccionar todo».
  await expect(bar.getByRole('button', { name: /^Seleccionar todo lo visible/ })).toHaveCount(0)

  await list.getByRole('button', { name: /^Salario/ }).click()
  await bar.getByRole('button', { name: 'Seleccionar todo lo visible (1)', exact: true }).click()
  await expect(bar).toContainText('1 seleccionada · RD$ 85,000')
  await expect(bar.getByRole('button', { name: /^Seleccionar todo lo visible/ })).toHaveCount(0)
  await list.getByRole('button', { name: /^Otros ingresos/ }).click()
  await expect(list.getByRole('checkbox', { checked: true })).toHaveCount(1)
  await page.getByRole('button', { name: 'Cancelar', exact: true }).click()
  await expect(bar).toHaveCount(0)
})

test('las elegidas que salen del filtro se sueltan y no vuelven', async ({ page }) => {
  const list = await filterCrypto(page)
  await page.getByRole('button', { name: 'Seleccionar', exact: true }).click()
  const bar = page.getByRole('region', { name: 'Acciones de la selección' })
  await list.getByRole('checkbox', { name: /^Seleccionar 8 ene MB DESDE/ }).check()
  await list.getByRole('checkbox', { name: /^Seleccionar 27 ene LBTR/ }).check()
  await expect(bar).toContainText('2 seleccionadas')

  const search = page.getByRole('search').getByRole('searchbox')
  await search.fill('MB DESDE')
  await expect(list.getByRole('checkbox')).toHaveCount(1)
  await expect(bar).toContainText('1 seleccionada · RD$ 12,000')
  await search.fill('P2P')
  await expect(list.getByRole('checkbox')).toHaveCount(3)
  await expect(bar).toContainText('1 seleccionada · RD$ 12,000')
  await expect(list.getByRole('checkbox', { name: /^Seleccionar 27 ene LBTR/ })).not.toBeChecked()
})

test('en escritorio la barra empieza donde empieza el contenido (no tapa el menú)', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1400, height: 900 })
  await filterCrypto(page)
  await page.getByRole('button', { name: 'Seleccionar', exact: true }).click()
  const bar = page.getByRole('region', { name: 'Acciones de la selección' })
  const nav = await page.getByRole('navigation', { name: 'Principal' }).boundingBox()
  const main = await page.getByRole('main').boundingBox()
  await expect
    .poll(async () => (await bar.boundingBox())?.x)
    .toBeCloseTo(main!.x, 0)
  expect(main!.x).toBeGreaterThanOrEqual(nav!.x + nav!.width - 1)
})
