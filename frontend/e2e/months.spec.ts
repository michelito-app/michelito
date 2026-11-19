import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py: hay diciembre 2025, enero y febrero 2026. Enero y
// febrero están en curso, así que el mes por defecto es diciembre 2025.
const title = (page: Page) => page.getByRole('heading', { level: 1 }).getByRole('button')
const grid = (page: Page) => page.getByRole('dialog', { name: 'Elegir mes' })
const nav = (page: Page) => page.getByRole('navigation', { name: 'Principal' })

test('transacciones: las flechas cambian de mes y conservan la búsqueda y los filtros', async ({
  page,
}) => {
  await page.goto('/transacciones?mes=2026-01&q=DEPOSITO&tipo=ingresos&agrupar=categoria')
  await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()
  await expect(page.getByRole('search').getByLabel('Mes')).toHaveCount(0)

  await page.getByRole('button', { name: 'Mes anterior' }).click()

  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
  const url = new URL(page.url())
  expect(url.searchParams.get('mes')).toBe('2025-12')
  expect(url.searchParams.get('q')).toBe('DEPOSITO')
  expect(url.searchParams.get('tipo')).toBe('ingresos')
  expect(url.searchParams.get('agrupar')).toBe('categoria')
  await expect(page.getByRole('searchbox')).toHaveValue('DEPOSITO')
  await expect(page.getByRole('search').getByLabel('Tipo')).toHaveValue('ingreso')
  await expect(page.getByRole('main').locator('header')).toContainText(
    'Movimientos del 1 al 31 de diciembre en todas tus cuentas',
  )

  await page.getByRole('button', { name: 'Mes siguiente' }).click()
  await expect(page).toHaveURL(/mes=2026-01/)
  await expect(page.getByRole('searchbox')).toHaveValue('DEPOSITO')
})

test('transacciones: «Volver a …» regresa al mes por defecto y conserva la búsqueda', async ({
  page,
}) => {
  await page.goto('/transacciones?mes=2026-02&q=FICTICIO')
  await page.getByRole('button', { name: 'Volver a Diciembre 2025' }).click()

  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
  await expect(page).not.toHaveURL(/mes=/)
  await expect(page).toHaveURL(/q=FICTICIO/)
  await expect(page.getByRole('button', { name: /Volver a/ })).toHaveCount(0)
})

for (const route of ['/', '/transacciones']) {
  test(`cuadrícula (${route}): salta a un mes de otro año`, async ({ page }) => {
    await page.goto(`${route}?mes=2026-02${route === '/' ? '' : '&q=FICTICIO'}`)
    await expect(title(page)).toHaveAttribute('aria-expanded', 'false')
    await title(page).click()

    await expect(title(page)).toHaveAttribute('aria-expanded', 'true')
    await expect(grid(page)).toContainText('2026')
    // Los meses sin datos no se eligen.
    await expect(grid(page).getByRole('button', { name: /^Marzo 2026/ })).toBeDisabled()
    await expect(grid(page).getByRole('button', { name: /^Febrero 2026/ })).toHaveAttribute(
      'aria-current',
      'date',
    )
    // Solo hay años con datos: no hay uno después de 2026.
    await expect(grid(page).getByRole('button', { name: 'Año siguiente' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )

    await grid(page).getByRole('button', { name: 'Año anterior' }).click()
    await expect(grid(page)).toContainText('2025')
    await grid(page).getByRole('button', { name: /^Diciembre 2025/ }).click()

    await expect(grid(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
    await expect(title(page)).toBeFocused()
    await expect(page).toHaveURL(/mes=2025-12/)
    if (route !== '/') await expect(page).toHaveURL(/q=FICTICIO/)
  })
}

test('cuadrícula: se maneja con el teclado', async ({ page }) => {
  await page.goto('/?mes=2026-02')
  await title(page).focus()
  await page.keyboard.press('Enter')

  // Al abrir, el foco está en el mes elegido.
  const february = grid(page).getByRole('button', { name: /^Febrero 2026/ })
  await expect(february).toBeFocused()
  await page.keyboard.press('ArrowLeft')
  await expect(grid(page).getByRole('button', { name: /^Enero 2026/ })).toBeFocused()
  // A la derecha de febrero no hay meses con datos: el foco se queda.
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await expect(february).toBeFocused()

  // Escape cierra y devuelve el foco al título.
  await page.keyboard.press('Escape')
  await expect(grid(page)).toHaveCount(0)
  await expect(title(page)).toBeFocused()

  await page.keyboard.press('Enter')
  await page.keyboard.press('ArrowLeft')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()
  await expect(page).toHaveURL(/mes=2026-01/)
})

test('cuadrícula: un clic fuera la cierra', async ({ page }) => {
  await page.goto('/?mes=2026-02')
  await title(page).click()
  await expect(grid(page)).toBeVisible()
  // Una esquina vacía de la página, lejos del panel.
  await page.getByRole('main').click({ position: { x: 4, y: 4 } })
  await expect(grid(page)).toHaveCount(0)
  await expect(page).toHaveURL(/mes=2026-02/)
})

test('el menú lleva el mes entre Resumen y Transacciones', async ({ page }) => {
  // En el mes por defecto los enlaces van sin mes.
  await page.goto('/')
  await expect(nav(page).getByRole('link', { name: 'Transacciones' })).toHaveAttribute(
    'href',
    '/transacciones',
  )

  await page.goto('/?mes=2026-01')
  await nav(page).getByRole('link', { name: 'Transacciones' }).click()
  await expect(page).toHaveURL(/\/transacciones\?mes=2026-01$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()

  // Desde Transacciones, solo el mes viaja: ni la búsqueda ni los filtros.
  await page.getByRole('button', { name: 'Mes siguiente' }).click()
  await page.getByRole('searchbox').fill('FICTICIO')
  await expect(page).toHaveURL(/q=FICTICIO/)
  await expect(nav(page).getByRole('link', { name: 'Resumen' })).toHaveAttribute(
    'href',
    '/?mes=2026-02',
  )
  // Las demás pantallas no llevan mes.
  await expect(nav(page).getByRole('link', { name: 'Pendientes' })).toHaveAttribute(
    'href',
    '/pendientes',
  )
  await nav(page).getByRole('link', { name: 'Resumen' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Febrero 2026' })).toBeVisible()
  await expect(page).toHaveURL(/\/\?mes=2026-02$/)

  // De vuelta al mes por defecto, el enlace ya no lleva mes.
  await page.getByRole('button', { name: 'Volver a Diciembre 2025' }).click()
  await expect(nav(page).getByRole('link', { name: 'Transacciones' })).toHaveAttribute(
    'href',
    '/transacciones',
  )
})

test('en 390 px: sin desplazamiento a los lados y la cuadrícula como hoja inferior', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const route of ['/?mes=2026-02', '/transacciones?mes=2026-02']) {
    await page.goto(route)
    await expect(page.getByRole('heading', { level: 1, name: 'Febrero 2026' })).toBeVisible()
    await title(page).click()
    await expect(grid(page)).toBeVisible()
    // Pegada abajo y de lado a lado (cuando termina de entrar).
    await expect
      .poll(async () => {
        const box = (await grid(page).boundingBox())!
        return [box.x, box.width, box.y + box.height].map(Math.round)
      }, { message: route })
      .toEqual([0, 390, 844])
    // Toques de al menos 44 px.
    for (const height of await grid(page)
      .getByRole('button')
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height)))
      expect(height, route).toBeGreaterThanOrEqual(44)
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width, route).toBeLessThanOrEqual(390)

    await grid(page).getByRole('button', { name: /^Enero 2026/ }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    )
  }
})

test('en 390 px: la hoja es modal; tocar el fondo la cierra y el foco vuelve al título', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?mes=2026-02')
  await title(page).click()
  await expect(grid(page)).toHaveAttribute('aria-modal', 'true')

  // Tab da la vuelta dentro de la hoja (año anterior y el mes elegido; el año siguiente no
  // tiene a dónde ir pero sigue enfocable).
  for (let i = 0; i < 5; i++) {
    await page.keyboard.press('Tab')
    expect(await grid(page).evaluate((el) => el.contains(document.activeElement))).toBe(true)
  }

  // El fondo oscurecido, por encima de la hoja.
  await page.mouse.click(195, 100)
  await expect(grid(page)).toHaveCount(0)
  await expect(title(page)).toBeFocused()
  await expect(page).toHaveURL(/mes=2026-02/)
})
