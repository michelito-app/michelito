import { expect, test, type Page } from '@playwright/test'

// Distribución del Resumen con los datos inventados de tests/e2e_server.py. Febrero 2026 trae
// cuatro avisos en «Para revisar»; enero 2026, ninguno. Lo que falta para probar (más
// categorías, más avisos, un análisis largo) se agrega sobre la respuesta real.
const FEBRUARY = '2026-02'
const JANUARY = '2026-01'

const reviewCard = (page: Page) => page.getByRole('region', { name: /Para revisar/ })

/** Avisos inventados: otras pruebas marcan como revisados los de febrero en la misma base. */
function reviewItems(count: number) {
  return Array.from({ length: count }, (_, n) => ({
    kind: n % 2 === 0 ? 'tercero_grande' : 'unico',
    fingerprint: `huella-inventada-${n + 1}`,
    day: '2026-02-13',
    month: FEBRUARY,
    merchant: `COMERCIO INVENTADO ${n + 1}`,
    description: `COMERCIO INVENTADO ${n + 1} SANTIAGO`,
    account_label: 'FICTICIO Cuenta corriente 777-0',
    amount_cents: 6_370_000,
    currency: 'DOP',
    amount_dop_cents: null,
    reason: 'Transferencia a terceros de RD$ 63,700 (desde RD$ 25,000 se revisa)',
    reviewed: false,
  }))
}

async function fakeReview(page: Page, count: number) {
  await page.route('**/api/review?**', (route) => route.fulfill({ json: reviewItems(count) }))
}

test.describe('resumen en cuadrícula', () => {
  test.use({ viewport: { width: 1440, height: 900 } })

  test('Categorías y Para revisar van lado a lado con el mismo alto', async ({ page }) => {
    await fakeReview(page, 4)
    await page.goto(`/?mes=${FEBRUARY}`)
    const categories = page.getByRole('region', { name: 'Categorías' })
    await expect(reviewCard(page)).toContainText('COMERCIO INVENTADO 4')
    const left = (await categories.boundingBox())!
    const right = (await reviewCard(page).boundingBox())!
    expect(Math.abs(left.y - right.y)).toBeLessThanOrEqual(1)
    expect(right.x).toBeGreaterThan(left.x + left.width)
    // Ninguna columna queda más larga que la otra.
    expect(Math.abs(left.height - right.height)).toBeLessThanOrEqual(1)
  })

  test('sin nada que revisar, la tarjeta queda en una línea y Categorías toma el ancho', async ({
    page,
  }) => {
    await page.goto(`/?mes=${JANUARY}`)
    await expect(reviewCard(page)).toContainText('Nada que revisar este mes ✓')
    const card = (await reviewCard(page).boundingBox())!
    expect(card.height).toBeLessThan(80)
    const categories = (await page.getByRole('region', { name: 'Categorías' }).boundingBox())!
    expect(categories.width).toBeGreaterThan(1000)
  })

  test('Para revisar muestra 4 y «Ver todos» despliega el resto', async ({ page }) => {
    await fakeReview(page, 7)
    await page.goto(`/?mes=${FEBRUARY}`)
    const card = reviewCard(page)
    await expect(card).toContainText('Para revisar (7)')
    await expect(card.getByRole('listitem')).toHaveCount(4)
    const more = card.getByRole('button', { name: 'Ver todos (7)' })
    await more.click()
    await expect(card.getByRole('listitem')).toHaveCount(7)
    await expect(card).toContainText('COMERCIO INVENTADO 7')
    await expect(card.getByRole('button', { name: 'Ver menos' })).toHaveAttribute('aria-expanded', 'true')
  })

  test('Categorías muestra las 8 de más gasto y «Ver las N» despliega el resto', async ({ page }) => {
    await page.route('**/api/summary**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const extra = Array.from({ length: 8 }, (_, n) => ({
        ...body.categories[0],
        category: `Inventada ${n + 1}`,
        amount_cents: 1_000 + n,
      }))
      await route.fulfill({ response, json: { ...body, categories: [...body.categories, ...extra] } })
    })
    await page.goto(`/?mes=${FEBRUARY}`)
    const categories = page.getByRole('region', { name: 'Categorías' })
    await expect(categories.getByRole('link')).toHaveCount(8)
    const more = categories.getByRole('button', { name: /^Ver las \d+$/ })
    const total = Number((await more.textContent())!.replace('Ver las ', ''))
    expect(total).toBeGreaterThan(8)
    await more.click()
    await expect(categories.getByRole('link')).toHaveCount(total)
  })
})

test.describe('lectura del mes', () => {
  test('pestañas solo con contenido; las flechas cambian de pestaña y «Leer más» abre', async ({
    page,
  }) => {
    const long = Array.from({ length: 8 }, (_, n) => `Párrafo inventado número ${n + 1}.`).join('\n\n')
    await page.route(`**/api/insights/${FEBRUARY}`, (route) =>
      route.fulfill({
        json: {
          month: FEBRUARY,
          label: 'Febrero 2026',
          text: long,
          accounts: null,
          created_at: '2026-03-02T10:00:00',
          updated_at: '2026-03-02T10:00:00',
          stale: false,
        },
      }),
    )
    await page.route('**/api/summary**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const changes = [
        { category: 'Viajes', diff_cents: 4_000_000, one_offs_cents: 0, purchases: 1, habitual_purchases: 0 },
      ]
      await route.fulfill({ response, json: { ...body, changes } })
    })
    await page.goto(`/?mes=${FEBRUARY}`)
    const card = page.getByRole('region', { name: 'Lectura del mes' })
    const tabs = card.getByRole('tab')
    // Febrero no es atípico: no hay «Qué pasó».
    await expect(tabs).toHaveText(['Análisis', 'Qué cambió'])
    await expect(card.getByRole('tab', { name: 'Análisis' })).toHaveAttribute('aria-selected', 'true')

    // Plegada: el final del análisis no se ve hasta «Leer más».
    const panel = card.getByRole('tabpanel')
    await expect(panel.getByText('Párrafo inventado número 8.')).not.toBeInViewport()
    await panel.getByRole('button', { name: 'Leer más' }).click()
    await expect(panel.getByText('Párrafo inventado número 8.')).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Leer menos' })).toHaveAttribute('aria-expanded', 'true')

    await panel.getByRole('button', { name: 'Leer menos' }).click()
    // Con el teclado, entrar en lo plegado lo abre.
    await panel.getByRole('link', { name: 'Editar en Reportes' }).focus()
    await expect(panel.getByRole('button', { name: 'Leer menos' })).toBeVisible()

    await card.getByRole('tab', { name: 'Análisis' }).focus()
    await page.keyboard.press('End')
    await expect(card.getByRole('tab', { name: 'Qué cambió' })).toBeFocused()
    await page.keyboard.press('Home')
    await expect(card.getByRole('tab', { name: 'Análisis' })).toBeFocused()
    await page.keyboard.press('ArrowRight')
    await expect(card.getByRole('tab', { name: 'Qué cambió' })).toBeFocused()
    await expect(card.getByRole('tab', { name: 'Qué cambió' })).toHaveAttribute('aria-selected', 'true')
    await expect(panel).toContainText('Viajes')
    await expect(panel).toHaveAttribute('tabindex', '0')
  })

  test('sin nada que leer, una línea ofrece copiar el comando', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.goto(`/?mes=${JANUARY}`)
    const card = page.getByRole('region', { name: 'Lectura del mes' })
    await expect(card).toContainText('Aún no hay lectura de este mes')
    await expect(card.getByRole('tab')).toHaveCount(0)
    const copy = card.getByRole('button', { name: `Copiar el comando finanzas analisis ${JANUARY}` })
    await copy.click()
    await expect(copy).toHaveText('Copiado')
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`finanzas analisis ${JANUARY}`)
  })
})

/** Doce meses inventados: julio y agosto atípicos (vecinos) y diciembre con dos marcas. */
async function twelveMonths(page: Page) {
  await page.route('**/api/summary**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    const months = Array.from({ length: 12 }, (_, n) => {
      const at = 2025 * 12 + 2 + n // marzo 2025 … febrero 2026
      return `${Math.floor(at / 12)}-${String((at % 12) + 1).padStart(2, '0')}`
    })
    const trend = months.map((month, n) => ({
      month,
      label: ['mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic', 'ene', 'feb'][n],
      total_cents: 2_000_000 + n * 50_000,
      income_cents: 8_000_000,
      partial: n === 11,
      spent_flag: n === 4 || n === 9 ? 'up' : null,
      spent_habitual_cents: 1_500_000,
      income_flag: n === 5 ? 'down' : n === 9 ? 'up' : null,
      income_habitual_cents: 6_000_000,
    }))
    await route.fulfill({ response, json: { ...body, trend } })
  })
}

type Box = { x: number; y: number; width: number; height: number }

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

test.describe('últimos 12 meses', () => {
  for (const width of [1440, 1024, 390]) {
    test(`${width} px: las marcas de meses atípicos no chocan ni se salen de su mes`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await twelveMonths(page)
      await page.goto(`/?mes=${FEBRUARY}`)
      const chart = page.getByRole('region', { name: 'Últimos 12 meses' })
      const marks = chart.getByTestId('trend-mark')
      await expect(marks).toHaveCount(4)
      const boxes = await marks.evaluateAll((els) =>
        els.map((el) => {
          const box = el.getBoundingClientRect()
          const column = el.closest('button')!.getBoundingClientRect()
          return {
            box: { x: box.x, y: box.y, width: box.width, height: box.height },
            inside: box.left >= column.left - 0.5 && box.right <= column.right + 0.5,
          }
        }),
      )
      for (const [i, mark] of boxes.entries()) {
        expect(mark.inside, `marca ${i} dentro de su mes`).toBe(true)
        for (const other of boxes.slice(i + 1)) expect(overlaps(mark.box, other.box)).toBe(false)
      }
      if (width === 1440) {
        // Con ancho, las marcas dicen qué pasó; la de dos marcas va una sobre otra.
        await expect(marks.nth(0)).toHaveText('▲ gasto alto')
        await expect(marks.nth(1)).toHaveText('▼ ingresos bajos')
      }
    })
  }

  test('390 px: el detalle de cada mes queda dentro de la pantalla', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await twelveMonths(page)
    await page.goto(`/?mes=${FEBRUARY}`)
    const columns = page.getByRole('list', { name: 'Meses' }).getByRole('button')
    for (const index of [0, 5, 11]) {
      await columns.nth(index).focus()
      const tip = page.getByTestId('trend-tip')
      await expect(tip).toBeVisible()
      const box = (await tip.boundingBox())!
      expect(box.x, `mes ${index + 1}`).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width, `mes ${index + 1}`).toBeLessThanOrEqual(390)
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(scroll).toBeLessThanOrEqual(390)
    }
  })

  test('tocar el mes elegido muestra y oculta su detalle', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await twelveMonths(page)
    await page.goto(`/?mes=${FEBRUARY}`)
    const chosen = page.getByRole('list', { name: 'Meses' }).getByRole('button', { name: /^febrero 2026/ })
    await expect(chosen).toHaveAttribute('aria-current', 'true')
    await chosen.click()
    await expect(page.getByTestId('trend-tip')).toBeVisible()
    await chosen.click()
    await expect(page.getByTestId('trend-tip')).toHaveCount(0)
    await expect(page).toHaveURL(new RegExp(`mes=${FEBRUARY}`))
  })
})

test.describe('lectura del mes: por qué no hay cambios', () => {
  test('mes en curso: se compara cuando cierran las cuentas', async ({ page }) => {
    await page.goto(`/?mes=${JANUARY}`)
    await expect(page.getByRole('region', { name: 'Lectura del mes' })).toContainText(
      'Qué cambió: se compara cuando todas las cuentas cierran el mes.',
    )
  })

  test('sin mes completo anterior: hace falta uno para comparar', async ({ page }) => {
    await page.goto('/?mes=2025-12')
    await expect(page.getByRole('region', { name: 'Lectura del mes' })).toContainText(
      'Qué cambió: hace falta al menos un mes completo anterior para comparar.',
    )
  })

  test('con lo habitual y sin cambios: todo dentro de lo habitual', async ({ page }) => {
    await page.route('**/api/summary**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, habitual_cents: 2_000_000, changes: [] } })
    })
    await page.goto('/?mes=2025-12')
    await expect(page.getByRole('region', { name: 'Lectura del mes' })).toContainText(
      'Qué cambió: todas las categorías están dentro de lo habitual.',
    )
  })

  test('si el análisis no carga, lo dice y deja reintentar', async ({ page }) => {
    let calls = 0
    await page.route(`**/api/insights/${JANUARY}`, (route) => {
      calls += 1
      return route.fulfill({ status: 500, json: { detail: 'falla inventada' } })
    })
    await page.goto(`/?mes=${JANUARY}`)
    const card = page.getByRole('region', { name: 'Lectura del mes' })
    await expect(card).toContainText('No se pudo cargar el análisis')
    await expect(card).not.toContainText('Aún no hay lectura')
    const before = calls
    await card.getByRole('button', { name: 'Reintentar' }).click()
    await expect.poll(() => calls).toBeGreaterThan(before)
  })
})

test.describe('montos de Categorías', () => {
  // Una categoría grande con gasto único y otra nueva (sin gasto en los meses anteriores): las
  // cifras más anchas que puede mostrar la fila.
  async function wideCategories(page: Page) {
    await page.route('**/api/summary**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      const base = body.categories[0]
      const big = {
        ...base,
        category: 'Vehículo y combustible inventado',
        amount_cents: 15_082_700,
        habitual_cents: 245_000,
        diff_cents: 14_837_700,
        same: false,
        one_offs_cents: 12_000_000,
      }
      const fresh = { ...base, category: 'Inventada nueva', amount_cents: 7_547_600 }
      const isNew = { habitual_cents: 0, diff_cents: 7_547_600, same: false, one_offs_cents: 0 }
      const categories = [big, { ...fresh, ...isNew }, ...body.categories]
      await route.fulfill({ response, json: { ...body, categories } })
    })
  }

  for (const width of [1440, 1024, 390]) {
    test(`${width} px: montos con RD$, «nuevo» y nada se sale de la fila`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await wideCategories(page)
      await page.goto(`/?mes=${FEBRUARY}`)
      const categories = page.getByRole('region', { name: 'Categorías' })
      const big = categories.getByRole('link', { name: /Vehículo y combustible inventado/ })
      await expect(big).toContainText('RD$ 150,827')
      await expect(big).toContainText('+RD$ 148,377 · único')
      await expect(categories.getByRole('link', { name: /Inventada nueva/ })).toContainText(
        /RD\$ 75,476\s*nuevo/,
      )
      for (const row of await categories.getByRole('link').all()) {
        const fits = await row.evaluate((el) => el.scrollWidth <= el.clientWidth)
        expect(fits, (await row.textContent()) ?? '').toBe(true)
      }
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(scroll).toBeLessThanOrEqual(width)
      await page.screenshot({ path: `test-results/categorias-${width}.png`, fullPage: false })
      await categories.screenshot({ path: `test-results/categorias-card-${width}.png` })
    })
  }
})
