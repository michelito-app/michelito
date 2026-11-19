import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py (`_link_pending`): un regalo «Lo pagué por otra
// persona» para Luis (RD$ 4,000, 20 dic), un cambio en que diste RD$ primero y te deben US$ 100
// (3 dic) y otro en que te depositaron y debes US$ 200 (10 dic, nota «Cambio con Pedro»). Las
// pruebas de board.spec.ts pueden dejar otros pendientes: aquí se buscan estas filas.
const VISA = 'demo:credit_card'

function lists(page: Page) {
  return {
    owed: page.getByRole('region', { name: 'Te deben' }),
    owe: page.getByRole('region', { name: 'Debes' }),
  }
}

test('el menú abre Pendientes con una fila en cada lista', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name: 'Pendientes' }).click()
  await expect(page).toHaveURL(/\/pendientes$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Pendientes' })).toBeVisible()

  const { owed, owe } = lists(page)
  const gift = owed.getByRole('link', { name: /^Luis/ })
  // Un grupo se llama por su «Con quién» (o su nombre); la fecha es la de su gasto.
  await expect(gift).toContainText('20 dic 2025')
  await expect(gift).toContainText('RD$ 4,000')
  await expect(gift).toContainText(/hace \d+ días/)
  await expect(owed.getByRole('link', { name: /CAMBISTA/ })).toContainText('US$ 100.00')
  const cousin = owe.getByRole('link', { name: /PRIMO/ })
  await expect(cousin).toContainText('Cambio con Pedro')
  // A la tasa acordada del cambio (63.10), no a la más reciente.
  await expect(cousin).toContainText('US$ 200.00')
  await expect(cousin).toContainText('≈ RD$ 12,620 a 63.10')
  await expect(page.getByText(/tasa de febrero/)).toHaveCount(0) // ningún compartido en US$
  await expect(page.getByTestId('pending-owe')).toHaveText('RD$ 12,620')
})

test('una fila abre su pantalla y «Volver» regresa a Pendientes', async ({ page }) => {
  await page.goto('/pendientes')
  await lists(page).owe.getByRole('link', { name: /PRIMO/ }).click()
  await expect(page).toHaveURL(/\/transacciones\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/PRIMO/)
  await expect(page.getByTestId('exchange-line')).toContainText('pendiente US$ 200.00')

  await page.getByRole('link', { name: 'Volver' }).click()
  await expect(page).toHaveURL(/\/pendientes$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Pendientes' })).toBeVisible()
})

test('el widget del Resumen trae las cifras de todos los meses y lleva a Pendientes', async ({
  page,
}) => {
  await page.goto('/?mes=2026-02') // los pendientes inventados son de diciembre
  const widget = page.getByRole('region', { name: 'Pendientes' })
  await expect(widget).toContainText('De todos los meses')
  await expect(widget.getByTestId('pending-card-owe')).toHaveText('RD$ 12,620')
  const owed = await widget.getByTestId('pending-card-owed').textContent()
  const net = await widget.getByTestId('pending-card-net').textContent()

  await widget.getByRole('link', { name: 'Ver pendientes' }).click()
  await expect(page).toHaveURL(/\/pendientes$/)
  await expect(page.getByTestId('pending-owed')).toHaveText(owed ?? '')
  await expect(page.getByTestId('pending-net')).toHaveText(net ?? '')
  await expect(lists(page).owed.getByRole('link', { name: /^Luis/ })).toBeVisible()
})

test('el widget del Resumen lleva las cuentas elegidas', async ({ page }) => {
  await page.goto(`/?mes=2026-02&cuentas=${encodeURIComponent(VISA)}`)
  const widget = page.getByRole('region', { name: 'Pendientes' })
  await expect(widget.getByTestId('pending-card-owe')).toHaveText('RD$ 0')
  await widget.getByRole('link', { name: 'Ver pendientes' }).click()
  await expect(page).toHaveURL(/\/pendientes\?cuentas=/)
  await expect(lists(page).owe).toContainText('No debes nada')
})

test('con solo la VISA quedan sus gastos y ningún cambio', async ({ page }) => {
  await page.goto(`/pendientes?cuentas=${encodeURIComponent(VISA)}`)
  const { owed, owe } = lists(page)
  await expect(owed.getByRole('link', { name: /^Luis/ })).toBeVisible()
  await expect(owed.getByRole('link', { name: /CAMBISTA/ })).toHaveCount(0)
  await expect(owe).toContainText('No debes nada')
  await expect(page.getByTestId('pending-owe')).toHaveText('RD$ 0')
})

test('en 390 px no se desplaza a los lados', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/pendientes')
  await expect(lists(page).owe.getByRole('link', { name: /PRIMO/ })).toBeVisible()
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})
