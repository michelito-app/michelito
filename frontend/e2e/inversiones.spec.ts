import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py, diciembre 2025, en la cuenta de ahorro: envíos a
// Pedro (RD$ 300,000 el 2, RD$ 100,000 el 15 y uno chico de RD$ 1,500 el 18) y lo que volvió
// (RD$ 9,000 el 22 y RD$ 60,000 el 29); y el «Préstamo a Ana» (RD$ 50,000 que volvieron con
// RD$ 2,000 de más), ya cerrado. Las pruebas van en orden: la primera marca la inversión.

const DECEMBER = '2025-12'
const PEDRO = 'Negocio de Pedro'

function list(page: Page) {
  return page.getByRole('list', { name: 'Lista de inversiones' })
}

function row(page: Page, title: RegExp) {
  return list(page).getByRole('button', { name: title })
}

async function openTransaction(page: Page, name: RegExp) {
  await page.goto(`/transacciones?mes=${DECEMBER}`)
  await page.getByRole('region', { name: 'Lista de transacciones' }).getByRole('button', { name }).click()
  return page.getByRole('complementary')
}

test.describe.configure({ mode: 'serial' })

test('un débito se marca como inversión: no resta de lo que te quedó', async ({ page }) => {
  await page.goto(`/?mes=${DECEMBER}`)
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await expect(kpis.getByTestId('invested-note')).toHaveText('de eso, RD$ 50,000 fueron a inversiones')

  const detail = await openTransaction(page, /^MB A 0000000066.*RD\$ 300,000$/)
  const section = detail.getByRole('region', { name: 'Inversión' })
  await expect(section).toContainText('no resta de lo que te quedó')
  await section.getByRole('button', { name: 'Es una inversión…' }).click()

  await expect(page).toHaveURL(/\/transacciones\/[^/?]+$/)
  await page.getByLabel('Con quién').fill('Pedro')
  await page.getByLabel('Nombre (opcional)').fill(PEDRO)
  await page.getByRole('button', { name: 'Marcar como inversión' }).click()

  const panel = page.getByTestId('investment-panel')
  await expect(panel).toContainText('Inversión · Activa')
  await expect(panel).toContainText(PEDRO)
  await expect(panel.getByTestId('investment-line')).toContainText('AportadoRD$ 300,000')
  await expect(panel.getByTestId('investment-line')).toContainText('Por volverRD$ 300,000')
  // Su categoría la manda el vínculo.
  await expect(page.getByRole('main').locator('header')).toContainText('MB A 0000000066')

  await page.goto(`/?mes=${DECEMBER}`)
  await expect(kpis.getByTestId('invested-note')).toHaveText('de eso, RD$ 350,000 fueron a inversiones')
})

test('se enlazan un rendimiento y una devolución mixta', async ({ page }) => {
  const detail = await openTransaction(page, /^TRANSF PEDRO INVERSOR.*RD\$ 9,000$/)
  await detail.getByRole('region', { name: 'Inversión' }).getByRole('button', { name: 'Es de una inversión…' }).click()

  await expect(page.getByText(`¿Es un cobro de ${PEDRO}?`)).toBeVisible()
  // Por su nombre accesible propio: el de la etiqueta incluiría la opción elegida.
  await page
    .getByRole('combobox', { name: 'Inversión', exact: true })
    .selectOption({ label: `${PEDRO} · Activa` })
  await page.getByRole('radio', { name: 'Rendimiento', exact: true }).check()
  await page.getByRole('button', { name: 'Enlazar a la inversión' }).click()

  const panel = page.getByTestId('investment-panel')
  await expect(panel.getByTestId('investment-line')).toContainText('RendimientosRD$ 9,000')
  await expect(panel.getByRole('list', { name: 'Cobros de la inversión' })).toContainText('Rendimiento')

  // El de RD$ 60,000 es mixto: RD$ 50,000 de capital y el resto, rendimiento.
  await panel.getByRole('button', { name: 'Añadir un cobro' }).click()
  await panel.getByRole('button', { name: 'Añadir TRANSF PEDRO INVERSOR' }).click()
  await panel.getByRole('radio', { name: /^Mixto/ }).check()
  const capital = panel.getByLabel('Parte de capital (el resto es rendimiento)')
  await capital.fill('60000')
  await panel.getByRole('button', { name: 'Añadir a la inversión' }).click()
  await expect(panel.getByRole('alert')).toContainText('menor que el crédito')
  await capital.fill('50,000')
  await panel.getByRole('button', { name: 'Añadir a la inversión' }).click()

  const line = panel.getByTestId('investment-line')
  await expect(line).toContainText('Capital devueltoRD$ 50,000')
  await expect(line).toContainText('RendimientosRD$ 19,000')
  await expect(line).toContainText('Por volverRD$ 250,000')
  await expect(panel).toContainText('Mixto: RD$ 50,000 de capital + RD$ 10,000 de rendimiento')
})

test('«Para revisar» propone otro aporte y confirmarlo es un toque', async ({ page }) => {
  await page.goto(`/?mes=${DECEMBER}`)
  const card = page.getByRole('region', { name: /Para revisar/ })
  await expect(card).toContainText('¿Otro aporte?')
  await expect(card).toContainText(`¿Es otro aporte a ${PEDRO}?`)
  await expect(card).not.toContainText('RD$ 1,500') // el envío chico no se propone
  await card.getByRole('button', { name: /^Sí, es un aporte: MB A 0000000066/ }).click()
  await expect(card).not.toContainText('¿Otro aporte?')
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await expect(kpis.getByTestId('invested-note')).toHaveText('de eso, RD$ 450,000 fueron a inversiones')
  await kpis.getByRole('link', { name: 'de eso, RD$ 450,000 fueron a inversiones' }).click()
  await expect(page).toHaveURL(/\/inversiones$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Inversiones' })).toBeVisible()
})

test('la vista: una activa y una cerrada, chips y buscador', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name: 'Inversiones' }).click()
  await expect(page).toHaveURL(/\/inversiones$/)

  await expect(page.getByTestId('investments-pending')).toHaveText('≈ RD$ 350,000')
  await expect(page.getByTestId('investments-year')).toHaveText('≈ RD$ 0') // los cobros son de 2025
  await expect(page.getByTestId('investments-active')).toHaveText('1 activa')

  const chips = page.getByRole('group', { name: 'Estado' })
  await expect(chips.getByRole('button', { name: /^Activas/ })).toHaveAttribute('aria-pressed', 'true')
  const pedro = row(page, /^Negocio de Pedro/)
  await expect(pedro).toContainText('Activa')
  await expect(pedro.getByTestId('investment-stats')).toContainText('AportadoRD$ 400,000')
  await expect(pedro.getByTestId('investment-stats')).toContainText('Capital devueltoRD$ 50,000')
  await expect(pedro.getByTestId('investment-stats')).toContainText('RendimientosRD$ 19,000')
  await expect(pedro.getByTestId('investment-stats')).toContainText(/% anual aprox\.\d+\.\d %/)
  await expect(pedro).toContainText('último cobro 29 dic 2025')
  await expect(row(page, /^Préstamo a Ana/)).toHaveCount(0)

  await chips.getByRole('button', { name: /^Cerradas/ }).click()
  await expect(page).toHaveURL(/estado=cerradas/)
  await expect(row(page, /^Préstamo a Ana/)).toContainText('Cerrada')
  await expect(row(page, /^Préstamo a Ana/)).toContainText('RendimientosRD$ 2,000')
  await expect(row(page, /^Negocio de Pedro/)).toHaveCount(0)

  await chips.getByRole('button', { name: /^Todas/ }).click()
  const titles = await list(page).getByRole('button').allTextContents()
  // La última actividad primero: Pedro (29 dic) antes que Ana (26 dic).
  expect(titles.findIndex((t) => t.startsWith(PEDRO))).toBeLessThan(
    titles.findIndex((t) => t.startsWith('Préstamo a Ana')),
  )
  const search = page.getByRole('searchbox', { name: 'Buscar inversiones' })
  await search.fill('ana')
  await expect(page).toHaveURL(/q=ana/)
  await expect(row(page, /^Préstamo a Ana/)).toBeVisible()
  await expect(row(page, /^Negocio de Pedro/)).toHaveCount(0)
  await search.fill('300,000') // un monto
  await expect(row(page, /^Negocio de Pedro/)).toBeVisible()
  await expect(row(page, /^Préstamo a Ana/)).toHaveCount(0)
  await chips.getByRole('button', { name: /^Cerradas/ }).click()
  await expect(page.getByText('Ninguna inversión cerrada coincide con «300,000»')).toBeVisible()
})

test('una fila se despliega; «Gestionar…» y «Volver» regresan con ella desplegada', async ({
  page,
}) => {
  await page.goto('/inversiones')
  const pedro = row(page, /^Negocio de Pedro/)
  await expect(pedro).toHaveAttribute('aria-expanded', 'false')
  await pedro.click()
  await expect(pedro).toHaveAttribute('aria-expanded', 'true')
  await expect(page).toHaveURL(/inversion=\d+/)
  const contributions = page.getByRole('region', { name: `Aportes de ${PEDRO}` })
  await expect(contributions).toContainText('MB A 0000000066 (2 dic)')
  await expect(contributions).toContainText('RD$ 100,000')
  await expect(page.getByRole('region', { name: `Cobros de ${PEDRO}` })).toContainText(
    'Mixto: RD$ 50,000 de capital + RD$ 10,000 de rendimiento',
  )
  const back = page.url()

  await page.getByRole('link', { name: `Gestionar ${PEDRO}` }).click()
  await expect(page).toHaveURL(/\/transacciones\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/MB A 0000000066/)
  const panel = page.getByTestId('investment-panel')
  await expect(panel).toContainText(PEDRO)

  // Renombrar y «Dar por perdida» (y deshacerlo) desde su pantalla.
  await panel.getByLabel('Con quién').fill('Pedro Pérez')
  await panel.getByRole('button', { name: 'Guardar nombre' }).click()
  await expect(panel.getByRole('button', { name: 'Guardar nombre' })).toHaveCount(0)
  const lost = panel.getByRole('checkbox', { name: /Dar por perdida/ })
  await lost.click() // controlado: cambia cuando responde el servidor
  await expect(panel).toContainText('Inversión · Dada por perdida')
  await expect(lost).toBeChecked()
  await lost.click()
  await expect(panel).toContainText('Inversión · Activa')
  await expect(lost).not.toBeChecked()

  await page.getByRole('link', { name: 'Volver' }).click()
  await expect(page).toHaveURL(back)
  await expect(row(page, /^Negocio de Pedro/)).toHaveAttribute('aria-expanded', 'true')
  await expect(row(page, /^Negocio de Pedro/)).toBeFocused()
  await expect(row(page, /^Negocio de Pedro/)).toContainText('Pedro Pérez')
})

test('en 390 px no se desplaza a los lados y los toques miden 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/inversiones?estado=todas')
  await row(page, /^Negocio de Pedro/).click()
  await expect(page.getByRole('region', { name: `Aportes de ${PEDRO}` })).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const targets = page.getByRole('main').locator('button:visible, a:visible, input:visible')
  for (const target of await targets.all()) {
    const box = await target.boundingBox()
    expect(box?.height ?? 0, await target.evaluate((el) => el.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44)
  }

  // «Para revisar» con un cobro posible (tres botones): la fila se envuelve, no se sale.
  await page.route('**/api/review?**', (route) =>
    route.fulfill({
      json: [
        {
          kind: 'cobro_posible',
          fingerprint: 'huella-inventada-cobro',
          day: '2025-12-30',
          month: DECEMBER,
          merchant: 'TRANSF PEDRO INVERSOR FICTICIO CON NOMBRE LARGO',
          description: 'TRANSF DE PEDRO INVERSOR FICTICIO CON NOMBRE LARGO',
          account_label: 'FICTICIO Cuenta de ahorro 888-1',
          amount_cents: 1_250_000,
          currency: 'DOP',
          amount_dop_cents: 1_250_000,
          reason: `¿Es un cobro de ${PEDRO}?`,
          reviewed: false,
          investment_id: 1,
        },
      ],
    }),
  )
  await page.goto(`/?mes=${DECEMBER}`)
  const card = page.getByRole('region', { name: /Para revisar/ })
  const buttons = card.getByRole('button', { name: /^(Es rendimiento|Es capital|No es de la)/ })
  await expect(buttons).toHaveCount(3)
  for (const button of await buttons.all()) {
    const box = (await button.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
  }
  const reviewOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(reviewOverflow).toBeLessThanOrEqual(0)
  await page.unroute('**/api/review?**')

  // La pantalla de la inversión tampoco se sale.
  await page.goto('/inversiones?estado=todas')
  await row(page, /^Negocio de Pedro/).click()
  await page.getByRole('link', { name: `Gestionar ${PEDRO}` }).click()
  await expect(page.getByTestId('investment-panel')).toBeVisible()
  const managed = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(managed).toBeLessThanOrEqual(0)
})
