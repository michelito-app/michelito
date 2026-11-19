import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py: el regalo para Luis (RD$ 4,000, «Lo pagué por otra
// persona», pendiente), «Ropa de Marta» (RD$ 4,350 entre dos, saldada con RD$ 2,175 en
// efectivo) y la librería con Rosa (dada por perdida). board.spec.ts corre antes con la misma
// base y puede dejar otros grupos: aquí se buscan estas filas.

function groups(page: Page) {
  return page.getByRole('list', { name: 'Grupos compartidos' })
}

function row(page: Page, title: RegExp) {
  return groups(page).getByRole('button', { name: title })
}

test('el menú abre Compartidos con un grupo pendiente, uno saldado y uno perdido', async ({
  page,
}) => {
  await page.goto('/')
  await page
    .getByRole('navigation', { name: 'Principal' })
    .getByRole('link', { name: 'Compartidos' })
    .click()
  await expect(page).toHaveURL(/\/compartidos$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Compartidos' })).toBeVisible()

  const gift = row(page, /^Luis/)
  await expect(gift).toContainText('Te deben RD$ 4,000')
  await expect(gift).toContainText('1 gasto · 20 dic 2025')
  await expect(gift).toContainText('Pagaste RD$ 4,000 · nada devuelto')
  const clothes = row(page, /^Ropa de Marta/)
  await expect(clothes).toContainText('Saldado')
  await expect(clothes).toContainText('Marta · 1 gasto · 18 dic 2025')
  await expect(clothes).toContainText('Pagaste RD$ 4,350 · te devolvieron RD$ 2,175')
  await expect(row(page, /^Rosa/)).toContainText('Dado por perdido')

  await expect(page.getByTestId('shared-owed')).toHaveText(/^≈ RD\$ [\d,]+$/)
  await expect(page.getByTestId('shared-year')).toHaveText(/^≈ RD\$ [\d,]+$/)
  await expect(page.getByTestId('shared-open')).toHaveText(/^\d+ grupos? abiertos?$/)
  // Lo más reciente primero: el efectivo de Marta (10 ene) va antes que el regalo (20 dic).
  const titles = await groups(page).getByRole('button').allTextContents()
  const order = (prefix: string) => titles.findIndex((t) => t.startsWith(prefix))
  expect(order('Ropa de Marta')).toBeLessThan(order('Luis'))
})

test('los chips y el buscador filtran, y van en la URL', async ({ page }) => {
  await page.goto('/compartidos')
  const chips = page.getByRole('group', { name: 'Estado' })
  await expect(chips.getByRole('button', { name: /^Todos/ })).toHaveAttribute('aria-pressed', 'true')

  await chips.getByRole('button', { name: /^Saldados/ }).click()
  await expect(page).toHaveURL(/estado=saldados/)
  await expect(row(page, /^Ropa de Marta/)).toBeVisible()
  await expect(row(page, /^Luis/)).toHaveCount(0)

  await chips.getByRole('button', { name: /^Todos/ }).click()
  await expect(page).not.toHaveURL(/estado=/)
  const search = page.getByRole('searchbox', { name: 'Buscar grupos' })
  await search.fill('rosa')
  await expect(page).toHaveURL(/q=rosa/)
  await expect(row(page, /^Rosa/)).toBeVisible()
  await expect(row(page, /^Luis/)).toHaveCount(0)

  await search.fill('4,350') // un monto, como en los selectores
  await expect(row(page, /^Ropa de Marta/)).toBeVisible()
  await expect(row(page, /^Rosa/)).toHaveCount(0)

  await search.fill('regalos') // el comercio de un gasto
  await expect(row(page, /^Luis/)).toBeVisible()
  await chips.getByRole('button', { name: /^Perdidos/ }).click()
  await expect(page.getByText('Ningún grupo perdido coincide con «regalos»')).toBeVisible()
})

test('una fila se despliega; «Gestionar…» y «Volver» regresan con ella desplegada', async ({
  page,
}) => {
  await page.goto('/compartidos?estado=pendiente')
  const gift = row(page, /^Luis/)
  await expect(gift).toHaveAttribute('aria-expanded', 'false')
  await gift.click()
  await expect(gift).toHaveAttribute('aria-expanded', 'true')
  await expect(page).toHaveURL(/grupo=\d+/)
  const expenses = page.getByRole('region', { name: 'Gastos de Luis' })
  await expect(expenses).toContainText('TIENDA REGALOS (20 dic)')
  await expect(expenses).toContainText('Lo pagaste por otra persona')
  await expect(expenses).toContainText('Pendiente RD$ 4,000')
  await expect(page.getByRole('region', { name: 'Reembolsos de Luis' })).toContainText(
    'Aún no te han devuelto nada',
  )
  const back = page.url()

  await page.getByRole('link', { name: 'Gestionar Luis' }).click()
  await expect(page).toHaveURL(/\/transacciones\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/TIENDA REGALOS/)

  await page.getByRole('link', { name: 'Volver' }).click()
  await expect(page).toHaveURL(back)
  const pending = page.getByRole('group', { name: 'Estado' }).getByRole('button', {
    name: /^Con pendiente/,
  })
  await expect(pending).toHaveAttribute('aria-pressed', 'true')
  await expect(row(page, /^Luis/)).toHaveAttribute('aria-expanded', 'true')
  await expect(row(page, /^Luis/)).toBeFocused() // su fila recibe el foco al volver
  await expect(page.getByRole('region', { name: 'Gastos de Luis' })).toBeVisible()
})

test('el grupo desplegado sigue en la lista aunque ya no coincida con el chip', async ({
  page,
}) => {
  await page.goto('/compartidos')
  await row(page, /^Luis/).click()
  await expect(page).toHaveURL(/grupo=\d+/)
  const group = new URL(page.url()).searchParams.get('grupo')

  // Como al volver de su pantalla tras cambiar el chip: Luis tiene pendiente, no está saldado.
  await page.goto(`/compartidos?estado=saldados&grupo=${group}`)
  await expect(row(page, /^Ropa de Marta/)).toBeVisible()
  const gift = row(page, /^Luis/)
  await expect(gift).toHaveAttribute('aria-expanded', 'true')
  await expect(gift).toContainText('Te deben RD$ 4,000') // con su estado actual
  await expect(gift).toBeFocused()

  // Plegarla y desplegarla no la saca; cambiar la búsqueda sí.
  await gift.click()
  await expect(gift).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('searchbox', { name: 'Buscar grupos' }).fill('ropa')
  await expect(row(page, /^Luis/)).toHaveCount(0)
  await expect(row(page, /^Ropa de Marta/)).toBeVisible()
})

test('con cuentas sin grupos lo dice y deja crear uno', async ({ page }) => {
  await page.goto(`/compartidos?cuentas=${encodeURIComponent('bhd:savings:999-1')}`)
  await expect(page.getByText('Ningún grupo en las cuentas elegidas')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Nuevo grupo…' })).toBeVisible()
})

test('«Nuevo grupo…» lleva al gasto con «Compartir» abierto', async ({ page }) => {
  await page.goto('/compartidos')
  await page.getByRole('button', { name: 'Nuevo grupo…' }).click()
  const panel = page.getByRole('region', { name: 'Nuevo grupo' })
  const list = panel.getByRole('list', { name: 'Gastos sin compartir' })
  await expect(list.getByRole('listitem').first()).toBeVisible()
  // Lo ya compartido y los retiros no están en toda la lista (no solo en lo visible).
  const search = panel.getByRole('searchbox')
  for (const text of ['regalos', 'retiro', 'libreria']) {
    await search.fill(text)
    await expect(panel.getByText(`Nada coincide con «${text}».`)).toBeVisible()
  }

  await search.fill('gasolinera')
  await panel.getByRole('button', { name: /^Compartir GASOLINERA/ }).click()
  await expect(page).toHaveURL(/\/transacciones\/[^/?]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/GASOLINERA/)
  await expect(page.getByRole('heading', { level: 2, name: 'Compartir' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Marcar compartido' })).toBeVisible()

  await page.getByRole('link', { name: 'Volver' }).click()
  await expect(page).toHaveURL(/\/compartidos$/)
})

test('«Nuevo grupo…» sugiere arriba la cena grande y deja el impuesto en «Ver más»', async ({
  page,
}) => {
  await page.goto('/compartidos')
  await page.getByRole('button', { name: 'Nuevo grupo…' }).click()
  const panel = page.getByRole('region', { name: 'Nuevo grupo' })
  await expect(panel).toContainText('RD$ 2,000 o más')
  const list = panel.getByRole('list', { name: 'Gastos sin compartir' })
  const tax = panel.getByRole('button', { name: /^Compartir IMPUESTO/ })
  // ASADOR FICTICIO CUMPLEANOS (RD$ 5,200, 9 feb): el sugerido más reciente, el primero.
  await expect(list.getByRole('listitem').first()).toContainText('ASADOR FICTICIO')
  await expect(tax).toHaveCount(0) // el impuesto de RD$ 3 no se sugiere

  await panel.getByRole('button', { name: /^Ver más \(\d+\)$/ }).click()
  await expect(tax).toBeVisible()
  await panel.getByRole('button', { name: 'Ver menos' }).click()
  await expect(tax).toHaveCount(0)

  // El buscador busca en toda la lista, también en lo que no se sugiere.
  await panel.getByRole('searchbox').fill('impuesto')
  await expect(tax).toBeVisible()
})

test('«Nuevo grupo…» con el teclado: el foco va al buscador y vuelve al botón', async ({
  page,
}) => {
  await page.goto('/compartidos')
  const trigger = page.getByRole('button', { name: 'Nuevo grupo…' })
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await trigger.focus()
  await page.keyboard.press('Enter')

  const panel = page.getByRole('region', { name: 'Nuevo grupo' })
  await expect(trigger).toHaveAttribute('aria-expanded', 'true')
  await expect(trigger).toHaveAttribute('aria-controls', (await panel.getAttribute('id')) ?? '')
  await expect(panel.getByRole('searchbox')).toBeFocused()
  await page.keyboard.type('cine')
  await expect(panel.getByRole('button', { name: /^Compartir CINE/ })).toBeVisible()

  await panel.getByRole('button', { name: 'Cerrar' }).focus()
  await page.keyboard.press('Enter')
  await expect(panel).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
})

test('a 390 px no hay scroll horizontal y los toques miden 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/compartidos')
  await row(page, /^Ropa de Marta/).click()
  await expect(page.getByRole('region', { name: 'Reembolsos de Ropa de Marta' })).toContainText(
    'A mano · Marta · efectivo',
  )
  await page.getByRole('button', { name: 'Nuevo grupo…' }).click()
  await expect(page.getByRole('list', { name: 'Gastos sin compartir' })).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
  const targets = page
    .getByRole('main')
    .locator('button:visible, a:visible, input:visible')
  for (const target of await targets.all()) {
    const box = await target.boundingBox()
    expect(box?.height ?? 0, await target.evaluate((el) => el.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(44)
  }
})
