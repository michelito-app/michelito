import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py, febrero 2026: en la VISA DEMO un supermercado (RD$
// 3,120.75, día 3), un taller (RD$ 1,500, día 4) y un cine (RD$ 640, día 7); en la cuenta
// corriente, una transferencia de Carola de RD$ 3,760.75 (día 9) que paga el supermercado y el
// cine. Al final se deshace el grupo: las demás pruebas ven los totales de siempre.
const FEBRUARY = '2026-02'

test.describe.configure({ mode: 'serial' })

async function openRow(page: Page, name: RegExp) {
  await page.goto(`/transacciones?mes=${FEBRUARY}`)
  const row = page.getByRole('region', { name: 'Lista de transacciones' }).getByRole('button', { name })
  await row.click()
  return row
}

/** Abre la pantalla del vínculo de la fila desde la línea «Compartido» o «Reembolso» del panel. */
async function openScreen(page: Page, name: RegExp, section = 'Compartido') {
  await openRow(page, name)
  await page
    .getByRole('complementary')
    .getByRole('region', { name: section })
    .getByRole('button', { name: /Compartir…|Gestionar…/ })
    .click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(name)
}

const expenses = (page: Page) => page.getByRole('list', { name: 'Gastos del grupo' })

test('«Compartir…» crea un grupo con «Con quién»', async ({ page }) => {
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  await page.getByRole('radio', { name: 'Lo pagué por otra persona' }).check()
  await page.getByLabel('Con quién (opcional)').fill('Carola y Rafael')
  await page.getByRole('button', { name: 'Marcar compartido' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 1 gasto' })).toBeVisible()
  await expect(page.getByTestId('shared-group')).toContainText('Carola y Rafael')
  await expect(page.getByTestId('shared-line')).toHaveText(
    'Tu parteRD$ 0DevueltoRD$ 0Te debenRD$ 3,121',
  )
})

test('«Compartir…» del cine lo suma al grupo con el reparto del último gasto', async ({ page }) => {
  await openScreen(page, /CINE INVENTADO/)
  const tabs = page.getByRole('tablist', { name: 'Cómo compartir' })
  await expect(tabs.getByRole('tab', { name: 'Grupo nuevo' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await tabs.getByRole('tab', { name: 'Sumarlo a un grupo' }).click()
  await expect(tabs.getByRole('tab', { name: 'Sumarlo a un grupo' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  const open = page.getByRole('list', { name: 'Grupos con pendiente' })
  await expect(open).toContainText('Carola y Rafael · te deben RD$ 3,121')
  await open.getByRole('button', { name: 'Sumarlo a Carola y Rafael' }).click()
  await expect(page.getByRole('radio', { name: 'Lo pagué por otra persona' })).toBeChecked()
  await page.getByRole('button', { name: 'Sumar al grupo' }).click()

  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 2 gastos' })).toBeVisible()
  await expect(page.getByTestId('shared-line')).toHaveText(
    'Tu parteRD$ 0DevueltoRD$ 0Te debenRD$ 3,761',
  )
  // La transacción abierta se resalta en la lista del grupo.
  const current = expenses(page).locator('[aria-current="true"]')
  await expect(current).toHaveCount(1)
  await expect(current).toContainText('CINE INVENTADO')
})

test('Pendientes muestra una fila por grupo', async ({ page }) => {
  await page.goto('/pendientes')
  const owed = page.getByRole('region', { name: 'Te deben' })
  const group = owed.getByRole('link', { name: /Carola y Rafael/ })
  await expect(group).toHaveCount(1)
  await expect(group).toContainText('2 gastos')
  await expect(group).toContainText('RD$ 3,761')
  await expect(owed.getByRole('link', { name: /SUPERMERCADO|CINE INVENTADO/ })).toHaveCount(0)

  await group.click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/SUPERMERCADO FICTICIO/)
  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 2 gastos' })).toBeVisible()
  // El panel del grupo: las personas («Con quién») y el nombre, con ejemplos en la etiqueta.
  await expect(page.getByLabel('Personas (ej.: Ana y Luis)')).toHaveValue('Carola y Rafael')
  await expect(page.getByLabel('Nombre del grupo (ej.: Viaje a la playa)')).toHaveValue('')
})

test('la transferencia sugerida por nombre salda los dos', async ({ page }) => {
  const transfer = await openRow(page, /TRANSF CAROLA/)
  await expect(transfer).toContainText('¿Reembolso?')
  const detail = page.getByRole('complementary')
  await expect(detail).toContainText('¿Reembolso de Carola y Rafael?')
  await detail.getByRole('button', { name: 'Sí, enlazar' }).click()
  await expect(detail.getByTestId('link-summary-reimbursement')).toHaveText(
    'Es reembolso de Carola y Rafael · saldado',
  )
  await expect(transfer).toContainText('Reembolso')

  await detail
    .getByRole('region', { name: 'Reembolso' })
    .getByRole('button', { name: 'Gestionar…' })
    .click()
  await expect(page.getByTestId('expense-status')).toHaveText(['Saldado', 'Saldado'])
  await expect(page.getByText(/^Te devolvieron/)).toHaveCount(0)
  const current = page.getByRole('list', { name: 'Reembolsos' }).locator('[aria-current="true"]')
  await expect(current).toContainText('TRANSF CAROLA')
})

test('lo devuelto de más avisa; el gasto que faltaba va primero y el aviso desaparece', async ({
  page,
}) => {
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  // También pagaron el taller, en efectivo: sobra hasta que se suma el gasto.
  await page.getByRole('button', { name: 'Agregar reembolso' }).click()
  await page.getByRole('button', { name: 'Me pagaron en efectivo o en otra cuenta' }).click()
  await page.getByLabel(/^Monto/).fill('1500')
  await page.getByRole('button', { name: 'Anotar reembolso' }).click()
  await expect(page.getByText(/^Te devolvieron RD\$ 1,500 más de lo que te debían/)).toBeVisible()

  await page.getByRole('button', { name: 'Agregar otro gasto' }).click()
  const options = page.getByRole('list', { name: 'Gastos que se pueden agregar' })
  // El que cabe en lo devuelto de más va primero, sin buscarlo.
  await expect(options.getByRole('listitem').first()).toContainText('TALLER')
  await options.getByRole('button', { name: /^Agregar TALLER/ }).click()
  await expect(page.getByRole('radio', { name: 'Lo pagué por otra persona' })).toBeChecked()
  await page.getByRole('button', { name: 'Sumar al grupo' }).click()

  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 3 gastos' })).toBeVisible()
  await expect(page.getByTestId('expense-status')).toHaveText(['Saldado', 'Saldado', 'Saldado'])
  await expect(page.getByText(/^Te devolvieron/)).toHaveCount(0)
  await expect(page.getByTestId('shared-line')).toHaveText(
    'Tu parteRD$ 0DevueltoRD$ 5,261Te debenRD$ 0',
  )
})

test('en 390 px la pantalla del grupo cabe sin desplazar a los lados', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  await expect(page.getByTestId('shared-group')).toBeVisible()
  await page.getByRole('button', { name: 'Agregar reembolso' }).click()
  await page.getByRole('button', { name: 'Me pagaron en efectivo o en otra cuenta' }).click()
  await expect(page.getByLabel('Dónde')).toBeVisible()
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
})

test('«Quitar del grupo»: los reembolsos se quedan; el último borra el grupo', async ({ page }) => {
  await openScreen(page, /SUPERMERCADO FICTICIO/)
  await page.getByRole('button', { name: /^Quitar TALLER.* del grupo$/ }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 2 gastos' })).toBeVisible()
  await expect(page.getByText(/^Te devolvieron RD\$ 1,500 más/)).toBeVisible()
  await expect(page.getByRole('list', { name: 'Reembolsos' })).toContainText('TRANSF CAROLA')

  await page.getByRole('button', { name: /^Quitar CINE INVENTADO.* del grupo$/ }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 1 gasto' })).toBeVisible()
  await page.getByRole('button', { name: /^Quitar SUPERMERCADO FICTICIO.* del grupo$/ }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Quitar el último gasto' })
  await expect(confirm).toContainText('se borra el grupo')
  // El foco entra al aviso y, al cancelar, vuelve al botón.
  await expect(confirm).toBeFocused()
  await confirm.getByRole('button', { name: 'Cancelar' }).click()
  const last = page.getByRole('button', { name: /^Quitar SUPERMERCADO FICTICIO.* del grupo$/ })
  await expect(last).toBeFocused()
  await last.click()
  await confirm.getByRole('button', { name: 'Sí, quitar y borrar el grupo' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Compartir' })).toBeVisible()

  const transfer = await openRow(page, /TRANSF CAROLA/)
  await expect(transfer).not.toContainText('Reembolso')
})

test('si una lista no carga, lo dice en vez de mostrarla vacía', async ({ page }) => {
  await page.route('**/api/shared/open', (route) => route.fulfill({ status: 500, body: 'x' }))
  await page.route('**/reimbursement-candidates', (route) =>
    route.fulfill({ status: 500, body: 'x' }),
  )
  await openScreen(page, /CINE INVENTADO/)
  await expect(page.getByRole('alert')).toContainText('No se pudieron cargar los grupos')

  await openScreen(page, /TRANSF CAROLA/, 'Reembolso')
  await expect(page.getByRole('alert')).toContainText('No se pudieron cargar los grupos')
})

test('si el selector de gastos o de créditos no carga, lo dice', async ({ page }) => {
  await openScreen(page, /CINE INVENTADO/)
  await page.getByLabel('Cuántos eran').fill('2')
  await page.getByRole('button', { name: 'Marcar compartido' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 1 gasto' })).toBeVisible()
  await page.route('**/expense-candidates', (route) => route.fulfill({ status: 500, body: 'x' }))
  await page.route('**/credit-candidates', (route) => route.fulfill({ status: 500, body: 'x' }))
  await page.getByRole('button', { name: 'Agregar otro gasto' }).click()
  await expect(page.getByRole('alert')).toContainText('No se pudieron cargar los gastos')
  await page.getByRole('button', { name: 'Agregar reembolso' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'créditos' })).toContainText(
    'No se pudieron cargar los créditos',
  )

  // Deja el cine como estaba.
  await page.getByRole('button', { name: /^Quitar CINE INVENTADO.* del grupo$/ }).click()
  await page.getByRole('button', { name: 'Sí, quitar y borrar el grupo' }).click()
  await expect(page.getByRole('heading', { level: 2, name: 'Compartir' })).toBeVisible()
})
