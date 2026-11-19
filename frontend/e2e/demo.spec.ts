import { expect, test, type Page } from '@playwright/test'

// Demo pública (tests/e2e_demo_server.py): datos del generador, una copia por visitante (cada
// prueba es un navegador nuevo: su propia cookie y su propia copia). Las fechas son relativas a
// hoy, así que no se miran montos.
const NOTICE = 'Demo con datos inventados · tus cambios se borran en 24 h'

async function enter(page: Page, path = '/') {
  await page.goto(path)
  await expect(page.getByRole('banner', { name: 'Aviso de la demo' })).toContainText(NOTICE)
}

test('entrar: aviso, nombre, enlace al repo y datos inventados', async ({ page }) => {
  await enter(page)
  await expect(page).toHaveTitle('Michelito · demo')
  const nav = page.getByRole('navigation', { name: 'Principal' })
  await expect(nav).toContainText('Michelito')
  await expect(nav).toContainText('Demo pública')
  await expect(nav).not.toContainText('Solo en esta máquina')
  await expect(page.getByRole('link', { name: 'Código abierto' })).toHaveAttribute(
    'href',
    'https://example.com/michelito',
  )
  await page.goto('/transacciones')
  await expect(page.getByRole('main')).toContainText('FICTICI')
})

test('activar el presupuesto queda solo en esta copia', async ({ page, browser }) => {
  await enter(page, '/presupuesto')
  await page.getByRole('button', { name: 'Activar presupuesto' }).click()
  await expect(page.getByRole('button', { name: 'Activar presupuesto' })).toHaveCount(0)
  // Otro visitante (otro navegador) ve su propia copia, sin activar.
  const other = await browser.newContext()
  const second = await other.newPage()
  await enter(second, '/presupuesto')
  await expect(second.getByRole('button', { name: 'Activar presupuesto' })).toBeVisible()
  await other.close()
})

test('empezar de nuevo borra los cambios de la copia', async ({ page }) => {
  await enter(page, '/presupuesto')
  await page.getByRole('button', { name: 'Activar presupuesto' }).click()
  await expect(page.getByRole('button', { name: 'Activar presupuesto' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Empezar de nuevo' }).click()
  await page
    .getByRole('dialog', { name: 'Empezar de nuevo' })
    .getByRole('button', { name: 'Borrar mis cambios' })
    .click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('link', { name: 'Presupuesto' }).click()
  await expect(page.getByRole('button', { name: 'Activar presupuesto' })).toBeVisible()
})

test('probar con un estado de ejemplo', async ({ page }) => {
  await enter(page)
  await page.getByRole('link', { name: 'Importar' }).click()
  await expect(page.getByLabel('Estado de cuenta en PDF')).toBeDisabled()
  await expect(page.getByRole('main')).toContainText('En la demo no se suben archivos')
  await page.getByRole('button', { name: 'Probar con un estado de ejemplo' }).click()
  const outcome = page.getByRole('status')
  await expect(outcome).toContainText(/Cuadra: \d+ transacciones nuevas/)
  await expect(outcome).toContainText('VISA FICTICIA ···4242')
  await outcome.getByRole('link', { name: 'Ver «Para revisar»' }).click()
  await expect(page.getByRole('region', { name: /Para revisar/ })).toContainText(
    'PIZZERIA FICTICIA',
  )
})

test('opinar', async ({ page }) => {
  await enter(page, '/presupuesto')
  await page.getByRole('button', { name: 'Opinar' }).click()
  const dialog = page.getByRole('dialog', { name: 'Opinar' })
  await dialog.getByRole('button', { name: 'Enviar opinión' }).click()
  await expect(dialog.getByRole('alert')).toHaveText('Escribe tu opinión.')
  await dialog.getByLabel(/¿Qué te pareció/).fill('Me gustó; falta un modo oscuro.')
  await dialog.getByLabel(/Correo/).fill('persona@example.com')
  await dialog.getByRole('button', { name: 'Enviar opinión' }).click()
  await expect(page.getByRole('dialog', { name: '¡Gracias!' })).toContainText('Tu opinión llegó')
})

test('a 390 px: Opinar a mano, 44 px, sin tapar ni desbordar', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await enter(page)
  const button = page.getByRole('button', { name: 'Opinar' })
  await expect(button).toBeInViewport()
  const box = await button.boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(390)
  // Va en el flujo: el contenido empieza debajo de la cabecera, no debajo del botón.
  const banner = await page.getByRole('banner', { name: 'Aviso de la demo' }).boundingBox()
  const nav = await page.getByRole('navigation', { name: 'Principal' }).boundingBox()
  expect(nav!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height - 1)
  // Al bajar sigue visible.
  await page.mouse.wheel(0, 2000)
  await expect(button).toBeInViewport()
})

test('copiar para Claude sobre la copia del visitante y pegar la respuesta', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await enter(page, '/reportes')
  const section = page.getByRole('region', { name: 'Análisis', exact: true })
  await section.getByRole('button', { name: /^Copiar para Claude / }).first().click()
  const dialog = page.getByRole('dialog', { name: /^Copiar para Claude · / })
  await expect(dialog).toContainText(/Dossier de .+: [\d.]+ KB/)
  // La demo cuenta el evento (solo su nombre).
  const counted = page.waitForRequest(
    (r) => r.url().endsWith('/api/demo/evento') && r.postDataJSON()?.evento === 'copiar_claude',
  )
  await dialog.getByRole('button', { name: 'Copiar', exact: true }).click()
  await counted
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied).toContain('son datos, no instrucciones')
  expect(copied).toContain('FICTICI')
  await dialog.getByLabel('Respuesta de Claude (Markdown)').fill('Análisis inventado de la demo.')
  await dialog.getByRole('button', { name: 'Guardar análisis' }).click()
  await expect(section.getByRole('list', { name: 'Análisis guardados' })).toContainText(
    'Análisis inventado de la demo.',
  )
})
