import { expect, test, type Page } from '@playwright/test'

// Servidor `--hogar` de tests/e2e_server.py (datos y proveedores inventados): una telefónica
// ficticia con cuatro nombres (TELFIC PAGO, IBANKING, P y WB; enero en dos pagos) y una
// recarga y una compra en su tienda (TELFIC AGORA), el AGUA FICTICIA (sin proveedor) y el «Acueducto Ficticio» de la lista sin pagos,
// el ALQUILER FICTICIO (Vivienda), un préstamo con un abono extra en enero y un SEGURO HOGAR
// suelto. Cada prueba deshace en la Bitácora lo que hizo: ninguna depende de otra.
const PHONE = 'Telefónica Ficticia'
const WATER = 'AGUA FICTICIA'
const WATER_PROVIDER = 'Acueducto Ficticio'
const INSURANCE = 'SEGURO HOGAR'
const RENT = 'ALQUILER FICTICIO'

function row(page: Page, name: string) {
  return page.getByRole('listitem').filter({
    has: page.getByRole('button', { name: `Marcar ${name}`, exact: true }),
  })
}

async function openActions(page: Page, name: string) {
  await page.getByRole('button', { name: `Marcar ${name}`, exact: true }).click()
  return page.getByRole('group', { name: `Marcas de ${name}`, exact: true })
}

/** Deshace en la Bitácora la entrada «subject · — → after» (la busca por `search`). */
async function undoInLog(page: Page, search: string, subject: string, after: string) {
  await page.goto('/bitacora')
  await page.getByRole('searchbox', { name: 'Buscar en la bitácora' }).fill(search)
  const line = `${subject} · — → ${after}`
  await page.getByRole('button', { name: `Deshacer: ${line}`, exact: true }).click()
  await expect(page.getByRole('main')).toContainText(`Deshecho: ${subject} · ${after} → —`)
}

test('los grupos van Vivienda, Préstamos, Servicios; el proveedor junta sus nombres', async ({
  page,
}) => {
  await page.goto('/recurrentes')
  const titles = page.getByRole('main').getByRole('heading', { level: 2 })
  await expect(titles.nth(0)).toHaveText(/^Vivienda/)
  await expect(titles.nth(1)).toHaveText(/^Préstamos/)
  await expect(titles.nth(2)).toHaveText(/^Servicios/)
  const phone = row(page, PHONE)
  await expect(phone).toContainText('Incluye: TELFIC IBANKING, TELFIC P, TELFIC PAGO, TELFIC WB')
  await expect(phone).toContainText('Variable')
  await expect(phone).toContainText('RD$ 1,500')
  await expect(row(page, 'AUT PAGO 0000000088')).toContainText(
    'abonos extra este año: RD$ 30,000',
  )
  await expect(row(page, RENT)).toBeVisible()
  await expect(page.getByRole('main')).not.toContainText('RECARGA')
  await expect(page.getByRole('main')).not.toContainText('AGORA')
})

test('«Grupo…» cambia el grupo del alquiler y se deshace en la Bitácora', async ({ page }) => {
  await page.goto('/recurrentes')
  const actions = await openActions(page, RENT)
  await actions.getByRole('button', { name: 'Grupo…' }).click()
  await actions
    .getByRole('combobox', { name: 'Grupo en Recurrentes', exact: true })
    .selectOption('otros')
  await actions.getByRole('button', { name: 'Guardar grupo' }).click()
  const others = page.getByRole('region', { name: /^Otros recurrentes/ })
  await expect(others.getByRole('button', { name: `Marcar ${RENT}`, exact: true })).toBeVisible()

  await undoInLog(page, RENT, RENT, 'sin marca, en Otros recurrentes')
  await page.goto('/recurrentes')
  const housing = page.getByRole('region', { name: /^Vivienda/ })
  await expect(housing.getByRole('button', { name: `Marcar ${RENT}`, exact: true })).toBeVisible()
})

test('«Unir con…» junta el agua con el acueducto y se deshace en la Bitácora', async ({ page }) => {
  await page.goto('/recurrentes')
  const actions = await openActions(page, WATER)
  await actions.getByRole('button', { name: 'Unir con…' }).click()
  await actions.getByRole('combobox', { name: 'Unir con', exact: true }).selectOption({
    label: WATER_PROVIDER,
  })
  await actions.getByRole('button', { name: 'Unir', exact: true }).click()
  await expect(row(page, WATER_PROVIDER)).toContainText(`Incluye: ${WATER}`)
  await expect(page.getByRole('button', { name: `Marcar ${WATER}`, exact: true })).toHaveCount(0)

  await undoInLog(page, WATER_PROVIDER, `${WATER} → ${WATER_PROVIDER}`, `con ${WATER_PROVIDER}`)
  await expect(page.getByRole('main')).toContainText('Unión de recurrentes')
  await page.goto('/recurrentes')
  await expect(row(page, WATER)).toBeVisible()
  await expect(page.getByRole('button', { name: `Marcar ${WATER_PROVIDER}` })).toHaveCount(0)
})

test('«Separar» saca un nombre del proveedor y se deshace en la Bitácora', async ({ page }) => {
  await page.goto('/recurrentes')
  const actions = await openActions(page, PHONE)
  await actions.getByRole('button', { name: 'Separar TELFIC P', exact: true }).click()
  await expect(row(page, PHONE)).toContainText('Incluye: TELFIC IBANKING, TELFIC PAGO, TELFIC WB')

  await undoInLog(page, 'TELFIC P', `TELFIC P · fuera de ${PHONE}`, 'por separado')
  await page.goto('/recurrentes')
  await expect(row(page, PHONE)).toContainText('TELFIC IBANKING, TELFIC P, TELFIC PAGO')
})

test('«Es recurrente…» desde el detalle marca un cobro suelto y lo lleva a Recurrentes', async ({
  page,
}) => {
  await page.goto('/transacciones?mes=2026-01')
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await list.getByRole('button', { name: new RegExp(INSURANCE) }).click()
  const section = page.getByRole('complementary').getByRole('region', { name: 'Recurrente' })
  await section.getByRole('button', { name: 'Es recurrente…' }).click()
  await section.getByRole('radio', { name: 'Cada año' }).check()
  await section.getByRole('combobox', { name: 'Grupo', exact: true }).selectOption('vivienda')
  await section.getByRole('button', { name: 'Marcar como recurrente' }).click()
  await expect(section.getByTestId('recurring-state')).toHaveText(
    `Es recurrente: ${INSURANCE} · Vivienda`,
  )

  await section.getByRole('link', { name: 'Ver en Recurrentes' }).click()
  await expect(page).toHaveURL(/\/recurrentes$/)
  const vivienda = page.getByRole('region', { name: /^Vivienda/ })
  await expect(vivienda.getByRole('listitem').filter({ hasText: INSURANCE })).toContainText(
    'anual',
  )

  await undoInLog(page, INSURANCE, INSURANCE, 'es recurrente, anual, en Vivienda')
  await page.goto('/recurrentes')
  await expect(page.getByRole('button', { name: `Marcar ${INSURANCE}` })).toHaveCount(0)
})

test('el detalle de un pago del proveedor dice que ya es recurrente', async ({ page }) => {
  await page.goto('/transacciones?mes=2026-01')
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await list.getByRole('button', { name: /TELFIC IBANKING/ }).click()
  const section = page.getByRole('complementary').getByRole('region', { name: 'Recurrente' })
  await expect(section.getByTestId('recurring-state')).toHaveText(
    `Es recurrente: ${PHONE} · Servicios`,
  )
  await expect(section.getByRole('button', { name: 'Es recurrente…' })).toHaveCount(0)
})

test('a 390 px Recurrentes no se desplaza a lo ancho y los toques miden 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/recurrentes')
  await expect(page.getByRole('heading', { level: 1, name: 'Recurrentes' })).toBeVisible()
  const actions = await openActions(page, PHONE)
  await actions.getByRole('button', { name: 'Unir con…' }).click()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const buttons = actions.getByRole('button')
  for (const button of await buttons.all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  const select = actions.getByRole('combobox', { name: 'Unir con', exact: true })
  expect((await select.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
})
