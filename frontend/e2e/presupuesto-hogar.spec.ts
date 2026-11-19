import { expect, test, type Page } from '@playwright/test'

// Servidor `--hogar` de tests/e2e_server.py (datos inventados): diciembre 2025 es el último mes
// completo (lo habitual sale de él), el alquiler es de RD$ 25,000 y el «MARBETE FICTICIO» de enero
// está marcado como recurrente anual, así Presupuesto sugiere una reserva para él. «Hoy» es el
// 20 de febrero de 2026. Cada prueba deshace en la Bitácora lo que hizo: ninguna depende de otra.
const TAX = 'MARBETE FICTICIO'
const RENT = 'Vivienda'

/** Deshace en la Bitácora la entrada cuyo botón se llama «Deshacer: <line>» (la busca). */
async function undo(page: Page, search: string, line: string | RegExp) {
  await page.goto('/bitacora')
  await page.getByRole('searchbox', { name: 'Buscar en la bitácora' }).fill(search)
  const name = typeof line === 'string' ? `Deshacer: ${line}` : line
  const button = page.getByRole('button', { name, exact: typeof line === 'string' })
  await button.first().click()
  await expect(page.getByRole('main')).toContainText('Deshecho:')
}

const ACTIVATED = /^Deshacer: Presupuesto · sin activar → \d+ categorías, \d+ con tope$/

async function activate(page: Page) {
  await page.goto('/presupuesto?mes=2025-12')
  await page.getByRole('button', { name: 'Activar presupuesto' }).click()
  await expect(page.getByRole('listitem', { name: RENT, exact: true })).toBeVisible()
}

test('activar el presupuesto, editar un tope y ver una categoría pasada', async ({ page }) => {
  await activate(page)
  const rent = page.getByRole('listitem', { name: RENT, exact: true })
  // Arranca con lo habitual redondeado (el alquiler de diciembre).
  await expect(rent).toContainText('RD$ 25,000 de RD$ 25,000')
  await rent.getByRole('button', { name: `Editar el tope de ${RENT}` }).click()
  await rent.getByRole('textbox', { name: `Tope de ${RENT} (RD$)` }).fill('20000')
  await rent.getByRole('button', { name: 'Guardar tope' }).click()
  await expect(rent).toContainText('RD$ 25,000 de RD$ 20,000 · pasó por RD$ 5,000')
  await expect(rent).toContainText('Tope a mano')
  // La que más pasa va primero.
  const lines = page.getByRole('region', { name: 'Categorías' }).getByTestId('budget-line')
  await expect(lines.first()).toHaveAccessibleName(RENT)

  // La tarjeta del Resumen cuenta las pasadas.
  await page.goto('/?mes=2025-12')
  const card = page.getByRole('region', { name: 'Presupuesto', exact: true })
  await expect(card.getByTestId('budget-status')).toContainText(/1 categoría pasada \(\+RD\$/)

  await undo(page, RENT, `${RENT} · tope RD$ 25,000 → tope RD$ 20,000`)
  await undo(page, 'Presupuesto', ACTIVATED)
  await page.goto('/presupuesto')
  await expect(page.getByRole('button', { name: 'Activar presupuesto' })).toBeVisible()
})

test('crear una reserva desde una sugerencia y vincularle un gasto', async ({ page }) => {
  await page.goto('/presupuesto')
  const suggestions = page.getByRole('group', { name: 'Sugerencias de reservas' })
  await expect(suggestions).toContainText(
    `¿Crear reserva “${TAX}” por ≈ RD$ 3,400 (vence en enero)?`,
  )
  await suggestions.getByRole('button', { name: `Crear reserva: ${TAX}` }).click()
  const reserves = page.getByRole('region', { name: 'Reservas' })
  const reserve = reserves.getByRole('listitem', { name: TAX, exact: true })
  await expect(reserve).toContainText('RD$ 300/mes')
  await expect(reserve).toContainText('Cada año en enero')
  await expect(page.getByRole('group', { name: 'Sugerencias de reservas' })).toHaveCount(0)

  // «Es de una reserva…» desde el detalle del gasto.
  await page.goto('/transacciones?mes=2026-01')
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await list.getByRole('button', { name: new RegExp(TAX) }).click()
  const section = page.getByRole('complementary').getByRole('region', { name: 'Reserva' })
  await section.getByRole('button', { name: 'Es de una reserva…' }).click()
  await section.getByRole('combobox', { name: 'Reserva', exact: true }).selectOption({ index: 0 })
  await section.getByRole('button', { name: 'Vincular', exact: true }).click()
  await expect(section.getByTestId('reserve-state')).toContainText(
    `Cubierto por la reserva ${TAX}`,
  )
  await expect(section).toContainText(
    'Para compartirlo o mandarlo a otro vínculo, primero quítalo de la reserva.',
  )

  await page.goto('/presupuesto')
  const linked = page
    .getByRole('region', { name: 'Reservas' })
    .getByRole('listitem', { name: TAX, exact: true })
  await expect(linked).toContainText('cubierto por la reserva')
  await expect(linked).toContainText('Este año: RD$ 3,400 de RD$ 3,400')

  await undo(page, TAX, `${TAX} · — → cubierto por «${TAX}»`)
  await undo(page, TAX, `${TAX} · — → RD$ 3,400 · cada año en enero`)
  await page.goto('/presupuesto')
  await expect(page.getByRole('button', { name: `Crear reserva: ${TAX}` })).toBeVisible()
})

test('una reserva que vence pronto sale en «Próximos gastos grandes» del Resumen', async ({
  page,
}) => {
  await page.goto('/presupuesto')
  await page.getByRole('button', { name: 'Nueva reserva…' }).click()
  const form = page.getByRole('form', { name: 'Nueva reserva' })
  await form.getByRole('textbox', { name: 'Nombre de la reserva' }).fill('Colegio ficticio')
  await form.getByRole('textbox', { name: 'Monto estimado (RD$)' }).fill('45000')
  await form.getByRole('combobox', { name: 'Categoría de la reserva' }).selectOption('Educación')
  await form.getByRole('radio', { name: 'Una vez' }).check()
  await form.getByLabel('Mes del vencimiento').fill('2026-03')
  await form.getByRole('button', { name: 'Crear reserva' }).click()
  const reserve = page.getByRole('listitem', { name: 'Colegio ficticio', exact: true })
  await expect(reserve).toContainText('Una vez, en marzo 2026')

  await page.goto('/')
  const upcoming = page.getByRole('group', { name: 'Próximos gastos grandes' })
  await expect(upcoming).toContainText('Colegio ficticio')
  await expect(upcoming).toContainText('RD$ 45,000')
  // «Te quedó» dice cuánto queda después de apartar (el número principal no cambia).
  await expect(page.getByTestId('reserves-note')).toContainText(
    'después de apartar para tus reservas (RD$ 22,500/mes)',
  )

  await undo(page, 'Colegio', 'Colegio ficticio · — → RD$ 45,000 · una vez, en 2026-03')
  await page.goto('/')
  await expect(page.getByRole('group', { name: 'Próximos gastos grandes' })).toContainText(
    'Ninguna reserva vence pronto.',
  )
})

test('a 390 px Presupuesto no se desplaza a lo ancho y los toques miden 44 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await activate(page)
  await page.getByRole('button', { name: 'Nueva reserva…' }).click()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const buttons = page.getByRole('main').getByRole('button')
  const count = await buttons.count()
  expect(count).toBeGreaterThan(5)
  for (let i = 0; i < count; i++) {
    const box = await buttons.nth(i).boundingBox()
    if (box) expect(box.height, await buttons.nth(i).innerText()).toBeGreaterThanOrEqual(44)
  }
  await undo(page, 'Presupuesto', ACTIVATED)
})
