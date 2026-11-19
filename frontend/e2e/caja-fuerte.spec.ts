import { expect, test, type Locator, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py: la caja fuerte empieza con un saldo inicial de
// US$ 200 (diciembre, a 63.10 ≈ RD$ 12,620). En enero 2026, en la cuenta corriente, un «RETIRO
// CAJERO SANTO DOMINGO» de RD$ 5,000 y un «DEPOSITO CLIENTE FICTICIO» de RD$ 12,000. Las pruebas
// van en orden y la última deshace lo que hicieron (el resto de las pruebas no cambia). Una prueba
// anterior (board.spec.ts) corrige el depósito a «Entre mis cuentas», que no puede venir de la
// caja: aquí se pasa a «Otros ingresos» y al final vuelve a la que tenía.

const JANUARY = '2026-01'
const BOX = 'manual:caja-fuerte'
const INCOME = 'Otros ingresos'
let depositCategory = INCOME

function categorySelect(detail: Locator) {
  // Por su nombre exacto: el de la etiqueta incluiría la opción elegida.
  return detail.getByRole('combobox', { name: 'Categoría', exact: true })
}

async function setCategory(detail: Locator, name: string) {
  await categorySelect(detail).selectOption(name)
  await detail.getByRole('button', { name: 'Guardar' }).click()
  await expect(categorySelect(detail)).toHaveValue(name)
  await expect(detail.getByRole('button', { name: 'Guardar' })).toBeDisabled()
}

async function openTransaction(page: Page, name: RegExp, query = '') {
  await page.goto(`/transacciones?mes=${JANUARY}${query}`)
  await page
    .getByRole('region', { name: 'Lista de transacciones' })
    .getByRole('button', { name })
    .click()
  return page.getByRole('complementary')
}

function card(page: Page) {
  return page.getByRole('region', { name: 'Caja fuerte' })
}

test.describe.configure({ mode: 'serial' })

test('un retiro se marca como guardado: deja de ser gasto y suma a la caja', async ({ page }) => {
  await page.goto(`/?mes=${JANUARY}`)
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await expect(kpis).toBeVisible()
  await expect(kpis.getByTestId('cash-box-note')).toHaveCount(0)

  const detail = await openTransaction(page, /^RETIRO CAJERO.*RD\$ 5,000$/)
  const section = detail.getByRole('region', { name: 'Caja fuerte' })
  await expect(section).toContainText('no cuenta como gasto hasta que lo uses')
  await section.getByRole('button', { name: 'Lo guardé en la caja fuerte' }).click()
  await expect(section.getByTestId('cash-box-text')).toContainText('Guardado en la caja fuerte')
  await expect(categorySelect(detail)).toBeDisabled()
  await expect(categorySelect(detail)).toHaveValue(
    'Caja fuerte',
  )

  await page.goto(`/?mes=${JANUARY}`)
  const note = kpis.getByTestId('cash-box-note')
  await expect(note).toHaveText('de eso, RD$ 5,000 fueron a la caja fuerte')
  await note.getByRole('link').click()
  await expect(page).toHaveURL(/\/cuentas#caja-fuerte$/)
  await expect(card(page).getByTestId('cash-box-balance')).toHaveText('RD$ 5,000 + US$ 200.00')
  await expect(card(page).getByTestId('cash-box-approx')).toHaveText('≈ RD$ 17,620')
  const lines = card(page).getByRole('list', { name: 'Movimientos de la caja fuerte' })
  await expect(lines).toContainText('Retiro guardado')
  await expect(lines).toContainText('Saldo inicial')
})

test('una salida se registra con su categoría y cuenta como gasto', async ({ page }) => {
  await page.goto('/cuentas')
  await card(page).getByRole('button', { name: 'Registrar salida…' }).click()
  const form = card(page).getByRole('region', { name: 'Registrar salida' })
  await form.getByLabel('Monto').fill('1,500')
  await expect(form.getByLabel('Fecha')).toHaveAttribute('min', '2000-01-01')
  await expect(form.getByLabel('Fecha')).toHaveAttribute('max', /^\d{4}-\d{2}-\d{2}$/)
  await form.getByLabel('Fecha').fill('2026-01-20')
  await form
    .getByRole('combobox', { name: 'Categoría', exact: true })
    .selectOption({ label: 'Supermercado' })
  await form.getByLabel('Nota (opcional)').fill('Colmado de prueba')
  await form.getByRole('button', { name: 'Guardar' }).click()
  await expect(form).toHaveCount(0)
  await expect(card(page).getByTestId('cash-box-balance')).toHaveText('RD$ 3,500 + US$ 200.00')
  const lines = card(page).getByRole('list', { name: 'Movimientos de la caja fuerte' })
  await expect(lines.getByRole('listitem').first()).toContainText('Supermercado · Colmado de prueba')

  // El filtro de cuentas: la caja es una cuenta más y la salida, un gasto de Supermercado.
  await page.goto(`/transacciones?mes=${JANUARY}&cuentas=${encodeURIComponent(BOX)}`)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button', { name: /^CAJA FUERTE/ })).toHaveCount(1)
  await expect(list.getByRole('button', { name: /RETIRO CAJERO/ })).toHaveCount(0)
  await list.getByRole('button', { name: /^CAJA FUERTE/ }).click()
  const detail = page.getByRole('complementary')
  await expect(categorySelect(detail)).toHaveValue(
    'Supermercado',
  )
  await expect(detail.getByRole('region', { name: 'Caja fuerte' })).toContainText(
    'cuenta como gasto en su categoría y mes',
  )
})

test('un depósito se vincula a la caja: no es ingreso y avisa del saldo negativo', async ({
  page,
}) => {
  const detail = await openTransaction(page, /^DEPOSITO CLIENTE.*RD\$ 12,000$/)
  depositCategory = await categorySelect(detail).inputValue()
  if (depositCategory !== INCOME) await setCategory(detail, INCOME)
  const section = detail.getByRole('region', { name: 'Caja fuerte' })
  await section.getByRole('button', { name: 'Vino de la caja fuerte', exact: true }).click()
  await expect(section.getByTestId('cash-box-text')).toHaveText(
    'Vino de la caja fuerte: no cuenta como ingreso.',
  )
  // RD$ 5,000 − 1,500 − 12,000: se permite, con aviso.
  await expect(section.getByTestId('cash-box-negative')).toHaveText(
    'La caja está en −RD$ 8,500; ¿ajustar el saldo inicial?',
  )

  await page.goto('/cuentas')
  await expect(card(page).getByTestId('cash-box-negative')).toHaveText(
    'La caja está en −RD$ 8,500; ¿ajustar el saldo inicial?',
  )
  // Antes de guardar, una salida más avisa cómo quedaría.
  await card(page).getByRole('button', { name: 'Registrar salida…' }).click()
  const form = card(page).getByRole('region', { name: 'Registrar salida' })
  await form.getByLabel('Monto').fill('500')
  await expect(form.getByTestId('cash-box-would-be-negative')).toHaveText(
    'La caja quedaría en −RD$ 9,000; ¿ajustar el saldo inicial?',
  )
  await form.getByRole('button', { name: 'Cancelar' }).click()
})

test('a 390 px la caja y las dos líneas del Resumen caben y se leen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/cuentas#caja-fuerte')
  await expect(card(page).getByTestId('cash-box-balance')).toBeVisible()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  for (const button of await card(page).getByRole('button').all()) {
    const box = await button.boundingBox()
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
  }

  // Con aportes y retiros guardados en el mismo mes salen las dos líneas, una debajo de otra.
  await page.route('**/api/summary**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, invested_cents: 35_000_000 } })
  })
  await page.goto(`/?mes=${JANUARY}`)
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  const invested = kpis.getByTestId('invested-note')
  const stored = kpis.getByTestId('cash-box-note')
  await expect(invested).toHaveText('de eso, RD$ 350,000 fueron a inversiones')
  await expect(stored).toHaveText('de eso, RD$ 5,000 fueron a la caja fuerte')
  const top = await invested.boundingBox()
  const bottom = await stored.boundingBox()
  expect(top && bottom).toBeTruthy()
  expect(bottom!.y).toBeGreaterThanOrEqual(top!.y + top!.height)
  for (const line of [top!, bottom!]) {
    expect(line.x).toBeGreaterThanOrEqual(0)
    expect(line.x + line.width).toBeLessThanOrEqual(390)
  }
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})

test('a 390 px la sección «Caja fuerte» del detalle cabe y sus toques miden 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const name of [/^RETIRO CAJERO.*RD\$ 5,000$/, /^DEPOSITO CLIENTE.*RD\$ 12,000$/]) {
    const detail = await openTransaction(page, name)
    const section = detail.getByRole('region', { name: 'Caja fuerte' })
    await section.scrollIntoViewIfNeeded()
    await expect(section.getByTestId('cash-box-text')).toBeVisible()
    const box = (await section.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
    for (const button of await section.getByRole('button').all()) {
      const size = (await button.boundingBox())!
      expect(size.height).toBeGreaterThanOrEqual(44)
      expect(size.x + size.width).toBeLessThanOrEqual(390)
    }
    for (const link of await section.getByRole('link').all()) {
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  }
})

test('se deshace todo: el depósito, el retiro guardado y la salida', async ({ page }) => {
  let detail = await openTransaction(page, /^DEPOSITO CLIENTE.*RD\$ 12,000$/)
  await detail.getByRole('button', { name: 'No vino de la caja' }).click()
  const section = detail.getByRole('region', { name: 'Caja fuerte' })
  await expect(section.getByTestId('cash-box-text')).toHaveText(
    '¿Era efectivo de la caja? Así no cuenta como ingreso.',
  )
  await expect(categorySelect(detail)).toHaveValue(INCOME)
  if (depositCategory !== INCOME) await setCategory(detail, depositCategory)

  detail = await openTransaction(page, /^RETIRO CAJERO.*RD\$ 5,000$/)
  await detail.getByRole('button', { name: 'No lo guardé (es gasto)' }).click()
  await expect(categorySelect(detail)).toHaveValue('Efectivo')

  // La salida se borra desde su detalle: el detalle se cierra y la URL ya no lleva ?tx=.
  detail = await openTransaction(page, /^CAJA FUERTE/, `&cuentas=${encodeURIComponent(BOX)}`)
  await expect(page).toHaveURL(/[?&]tx=caja-/)
  const manual = detail.getByRole('region', { name: 'Caja fuerte' })
  await manual.getByRole('button', { name: 'Borrar', exact: true }).click()
  await expect(page.getByRole('alertdialog', { name: 'Borrar el movimiento' })).toContainText(
    'Se borran también su nota y su categoría.',
  )
  await page.getByRole('button', { name: 'Sí, borrar' }).click()
  // Cerrado: el panel vuelve a «Detalle» vacío (en el teléfono, ni aparece).
  await expect(page.getByRole('complementary', { name: 'Detalle' })).toContainText(
    'Elige una transacción',
  )
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page).not.toHaveURL(/[?&]tx=/)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button', { name: /^CAJA FUERTE/ })).toHaveCount(0)

  await page.goto('/cuentas')
  await expect(card(page).getByTestId('cash-box-balance')).toHaveText('US$ 200.00')
  await expect(card(page).getByTestId('cash-box-negative')).toHaveCount(0)

  await page.goto(`/?mes=${JANUARY}`)
  await expect(page.getByRole('region', { name: 'Indicadores' })).toBeVisible()
  await expect(page.getByTestId('cash-box-note')).toHaveCount(0)
})
