import { expect, test, type Page } from '@playwright/test'

// Datos inventados de tests/e2e_server.py. Enero 2026 es un mes con compras de tres tarjetas.
// El servidor guarda una sola base: las pruebas que corrigen datos usan transacciones distintas
// (CAFE FICTICIO, GASOLINERA FICTICIA) y las demás no dependen del orden de las categorías.
const MONTH = '2026-01'
// Tarjeta inventada con un corte pagado a medias e intereses en el estado siguiente.
const INTEREST_CARD_PAGE = '/cuentas?cuenta=ficticio%3Acredit_card'

test('resumen: la primera categoría abre las transacciones filtradas', async ({ page }) => {
  await page.goto(`/?mes=${MONTH}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()

  await page.getByRole('region', { name: 'Categorías' }).getByRole('link').first().click()

  await expect(page).toHaveURL(/categoria=/)
  const category = new URL(page.url()).searchParams.get('categoria')!
  await expect(page.getByRole('heading', { level: 1, name: 'Transacciones' })).toBeVisible()
  const rows = page.getByRole('region', { name: 'Lista de transacciones' }).getByRole('button')
  await expect(rows.first()).toBeVisible()
  for (const row of await rows.all()) await expect(row).toContainText(category)
})

test('resumen: el flujo del mes muestra ingresos, gastos y lo que quedó', async ({ page }) => {
  // Enero 2026: nómina y un depósito de la cuenta corriente inventada más los créditos del
  // ahorro BHD; los gastos suman el retiro en cajero y el pago de préstamo. El pago de tarjeta
  // no cuenta. Antes Gastos 16,573, Te quedó 85,428 y 84 %: la demo ganó un pago de préstamo
  // (AUT PAGO, RD$ 2,000, gasto) y un envío a terceros (MB a, RD$ 3,000, solo resta de lo que
  // te quedó).
  await page.goto(`/?mes=${MONTH}`)
  await expect(page.getByText(/^Movimientos del 1 al 31 de enero en todas tus cuentas/)).toBeVisible()
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await expect(kpis).toContainText(/Ingresos\s*RD\$\s*102,001/)
  await expect(kpis).toContainText(/Gastos\s*RD\$\s*18,573/)
  await expect(kpis).toContainText(/Te quedó\s*RD\$\s*80,428/)
  await expect(kpis).toContainText(/% ahorrado\s*79 %/)
  // Lo de antes sigue a la vista.
  await expect(kpis).toContainText('Gastos únicos')
  await expect(kpis).toContainText('En dólares')
})

test('resumen: «Ver en qué se gastó» abre los gastos del mes agrupados por categoría', async ({
  page,
}) => {
  await page.goto(`/?mes=${MONTH}`)
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await kpis.getByRole('link', { name: 'Ver en qué se gastó', exact: true }).click()

  await expect(page).toHaveURL(/mes=2026-01/)
  await expect(page).toHaveURL(/tipo=gastos/)
  await expect(page).toHaveURL(/agrupar=categoria/)
  // El total de la lista es el mismo de la tarjeta Gastos del Resumen.
  await expect(page.getByRole('main').locator('header')).toContainText('RD$ 18,573')
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button').first()).toBeVisible()
  for (const row of await list.getByRole('button').all()) await expect(row).not.toContainText('Ingreso')
})

test('resumen: las transferencias a terceros restan de lo que te quedó y abren su lista', async ({
  page,
}) => {
  await page.goto(`/?mes=${MONTH}`)
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await expect(kpis).toContainText(/Transferencias a terceros\s*RD\$\s*3,000/)
  await expect(kpis).toContainText('Ingresos menos gastos y transferencias a terceros')
  // No es una categoría de gasto.
  await expect(
    page.getByRole('region', { name: 'Categorías' }).getByRole('link', { name: /Transferencias a terceros/ }),
  ).toHaveCount(0)

  await kpis.getByRole('link', { name: 'Ver transferencias a terceros', exact: true }).click()
  await expect(page).toHaveURL(/categoria=Transferencias\+a\+terceros/)
  await expect(page).toHaveURL(/mes=2026-01/)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button', { name: /^MB A .*RD\$ 3,000$/ })).toBeVisible()
  for (const row of await list.getByRole('button').all()) {
    await expect(row).toContainText('Transferencias a terceros')
  }
})

test('transacciones: el selector de categoría trae las categorías nuevas en su grupo', async ({
  page,
}) => {
  await page.goto(`/transacciones?mes=${MONTH}`)
  await page.getByRole('button', { name: /AUT PAGO/ }).click()
  const select = page.getByRole('complementary').getByLabel('Categoría')
  await expect(select).toHaveValue('Préstamos')
  await expect(select.locator('optgroup[label="Gastos"] option[value="Préstamos"]')).toHaveCount(1)
  await expect(
    select.locator('optgroup[label="Transferencias"] option[value="Transferencias a terceros"]'),
  ).toHaveCount(1)
})

test('resumen: si una cuenta bancaria corta antes, los ingresos dicen hasta cuándo', async ({
  page,
}) => {
  await page.route('**/api/summary**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, income_through: '2026-01-15', savings_rate: null } })
  })
  await page.goto(`/?mes=${MONTH}`)
  const kpis = page.getByRole('region', { name: 'Indicadores' })
  await expect(kpis).toContainText(/Ingresos\s*RD\$\s*102,001\s*Hasta\u00a0el\u00a015\u00a0ene/)
  await expect(kpis).toContainText(/% ahorrado\s*—\s*Ingresos hasta el 15 ene: no se calcula/)
})

test('resumen: un mes atípico se marca y «Qué pasó» enlaza sus movimientos', async ({ page }) => {
  // Los datos inventados no tienen meses suficientes para lo habitual: se marca diciembre a mano
  // con lo que mandaría el servidor (ver tests/test_anomalies.py para la regla).
  await page.route('**/api/summary**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    const trend = body.trend.map((t: { month: string }) =>
      t.month === '2025-12'
        ? { ...t, spent_flag: 'up', spent_habitual_cents: 500_000, income_flag: null }
        : t,
    )
    const what_happened = [
      {
        side: 'gasto',
        merchant: 'FERRETERIA INVENTADA',
        category: 'Hogar',
        amount_cents: 980_000,
        habitual_cents: 0,
        diff_cents: 980_000,
        count: 1,
        fingerprint: 'huella-inventada',
        day: '2025-12-06',
        description: 'FERRETERIA INVENTADA SANTIAGO',
      },
    ]
    await route.fulfill({ response, json: { ...body, trend, what_happened } })
  })
  await page.goto('/?mes=2025-12')
  const chart = page.getByRole('region', { name: 'Últimos 12 meses' })
  await expect(chart).toContainText('▲▼ meses atípicos: se apartan más de 30% (y RD$ 10,000)')
  await expect(chart.getByRole('button', { name: /^diciembre 2025.*gasto alto: Gasto RD\$ 19,883 · \+298% vs lo habitual/ })).toBeVisible()
  const reading = page.getByRole('region', { name: 'Lectura del mes' })
  await reading.getByRole('tab', { name: 'Qué pasó' }).click()
  const card = reading.getByRole('tabpanel')
  await expect(card).toContainText('Gastos más altos que lo habitual: RD$ 19,883; lo habitual es RD$ 5,000')
  const link = card.getByRole('link', { name: /Ver FERRETERIA INVENTADA: \+RD\$ 9,800/ })
  await expect(link).toHaveAttribute('href', '/transacciones?mes=2025-12&tx=huella-inventada')
})

test('resumen: un mes normal no lleva «Qué pasó»', async ({ page }) => {
  await page.goto('/?mes=2025-12')
  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Últimos 12 meses' })).not.toContainText('atípico')
  await expect(page.getByRole('tab', { name: 'Qué pasó' })).toHaveCount(0)
})

test('resumen: clic en una barra de los últimos 12 meses abre ese mes', async ({ page }) => {
  await page.goto(`/?mes=${MONTH}`)
  await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()
  const months = page.getByRole('region', { name: 'Últimos 12 meses' }).getByRole('list', { name: 'Meses' })

  // Al pasar el ratón sale el detalle del mes.
  await months.getByRole('button').first().hover()
  await expect(page.getByText(/^diciembre 2025$/i)).toBeVisible()

  // La primera columna es el mes más antiguo del gráfico (diciembre 2025 en los datos inventados).
  await months.getByRole('button').first().click()

  await expect(page).toHaveURL(/mes=2025-12/)
  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
  await expect(months.getByRole('button', { name: /^diciembre 2025/ })).toHaveAttribute('aria-current', 'true')

  // Con el teclado: desde enero, Mayús+Tab hasta diciembre y Enter.
  await page.goto(`/?mes=${MONTH}`)
  await months.getByRole('button', { name: /^enero 2026/ }).focus()
  await page.keyboard.press('Shift+Tab')
  await expect(months.getByRole('button', { name: /^diciembre 2025/ })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/mes=2025-12/)
  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
})

test('resumen: "Volver a" regresa al último mes completo y desaparece', async ({ page }) => {
  // En los datos inventados el último mes completo es diciembre 2025; enero está incompleto.
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Volver a/ })).toHaveCount(0)

  await page.getByRole('button', { name: 'Mes siguiente' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Enero 2026' })).toBeVisible()

  await page.getByRole('button', { name: 'Volver a Diciembre 2025' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Diciembre 2025' })).toBeVisible()
  await expect(page).not.toHaveURL(/mes=/)
  await expect(page.getByRole('button', { name: /Volver a/ })).toHaveCount(0)
})

test('resumen: las cifras de los indicadores nunca se parten en dos líneas', async ({ page }) => {
  // Montos grandes (millones) para forzar el caso que antes partía "RD$ / 1,274,490".
  await page.route('**/api/summary**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: {
        ...body,
        income_cents: 345678901,
        total_cents: 127449012,
        net_cents: 218229889,
        regular_total_cents: 127449012,
        one_offs_cents: 9876543,
        usd_cents: 6137512,
      },
    })
  })
  for (const width of [1440, 1232, 1000, 768, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(`/?mes=${MONTH}`)
    const values = page.getByText(/^(RD|US)\$ [\d,.]+$/)
    await expect(values.first()).toBeVisible()
    const lines = await values.evaluateAll((els) =>
      els.map((el) => {
        const box = el.getBoundingClientRect()
        const lineHeight = parseFloat(getComputedStyle(el).lineHeight)
        const card = el.parentElement!.getBoundingClientRect()
        return { text: el.textContent, oneLine: box.height < lineHeight * 1.5, fits: box.right <= card.right }
      }),
    )
    for (const line of lines) expect(line, `${width}px: ${line.text}`).toMatchObject({ oneLine: true, fits: true })
  }
})

test.describe('correcciones', () => {
  test.describe.configure({ mode: 'serial' })

  test('corregir una transacción mueve el monto de categoría', async ({ page }) => {
    await page.goto(`/transacciones?mes=${MONTH}`)
    await page.getByRole('button', { name: /CAFE FICTICIO/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel('Categoría').selectOption('Salud')
    await detail.getByLabel('Solo esta transacción').check()
    await detail.getByRole('button', { name: 'Guardar' }).click()

    await expect(page.getByRole('status').filter({ hasText: 'Guardado' })).toBeVisible()
    await expect(page.getByRole('button', { name: /CAFE FICTICIO/ })).toContainText('Corregida')

    await page.goto(`/?mes=${MONTH}`)
    const categories = page.getByRole('region', { name: 'Categorías' })
    await expect(categories.getByRole('link', { name: /Salud/ })).toContainText('300')
    // Restaurantes bajó de 2,150 a 1,850.
    await expect(categories.getByRole('link', { name: /Restaurantes/ })).toContainText('1,850')
  })

  test('corregir un depósito a «Entre mis cuentas» lo saca de los ingresos', async ({ page }) => {
    await page.goto(`/transacciones?mes=${MONTH}&tipo=ingresos`)
    await expect(page.getByRole('main')).toContainText('ingresos RD$ 102,001')
    await expect(page.getByRole('button', { name: /DEPOSITO CLIENTE/ })).toContainText(
      '+RD$ 12,000',
    )
    await page.getByRole('button', { name: /DEPOSITO CLIENTE/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel('Categoría').selectOption('Entre mis cuentas')
    await detail.getByLabel('Solo esta transacción').check()
    await detail.getByRole('button', { name: 'Guardar' }).click()

    await expect(page.getByRole('status').filter({ hasText: 'Guardado' })).toBeVisible()
    await expect(detail).toContainText('Ya no aparece con estos filtros')
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    await expect(list.getByRole('button', { name: /DEPOSITO CLIENTE/ })).toHaveCount(0)
    await expect(page.getByRole('main')).toContainText('ingresos RD$ 90,001')

    await page.goto(`/?mes=${MONTH}`)
    await expect(page.getByRole('region', { name: 'Indicadores' })).toContainText(
      /Ingresos\s*RD\$\s*90,001/,
    )
  })

  test('marcar un gasto único lo suma en «Gastos únicos»', async ({ page }) => {
    await page.goto(`/transacciones?mes=${MONTH}`)
    await page.getByRole('button', { name: /GASOLINERA FICTICIA/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel('Gasto único').check()
    await detail.getByRole('button', { name: 'Guardar' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Guardado' })).toBeVisible()

    await page.goto(`/?mes=${MONTH}`)
    await expect(page.getByRole('region', { name: 'Indicadores' })).toContainText(
      /Gastos únicos\s*RD\$\s*2,400/,
    )
  })
})

test('transacciones: el filtro Tipo = Ingresos deja solo los créditos que son ingreso', async ({
  page,
}) => {
  await page.goto(`/transacciones?mes=${MONTH}`)
  await page.getByRole('search').getByLabel('Tipo').selectOption('Ingresos')

  await expect(page).toHaveURL(/tipo=ingresos/)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button', { name: /DEPOSITO NOMINA/ })).toBeVisible()
  await expect(list.getByRole('button', { name: /CAFE FICTICIO|RETIRO CAJERO|SU PAGO/ })).toHaveCount(
    0,
  )
  const rows = await list.getByRole('button').all()
  expect(rows.length).toBeGreaterThan(0)
  for (const row of rows) await expect(row).toContainText('Ingreso')
  // Los ingresos van con "+" y en positivo, no como una devolución.
  await expect(list.getByRole('button', { name: /DEPOSITO NOMINA/ })).toContainText('+RD$ 85,000')
  // Sin gastos en la lista: el encabezado no muestra un total de gastos, solo los ingresos.
  const header = page.getByRole('main').locator('header')
  await expect(header).toContainText(/\d+ transacciones · ingresos RD\$ [\d,]+$/)
  await expect(header).not.toContainText('RD$ 0')
})

test('transacciones: las filas que no son gasto llevan su tipo', async ({ page }) => {
  await page.goto(`/transacciones?mes=${MONTH}`)
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  await expect(list.getByRole('button', { name: /PAGO TARJETA/ })).toContainText('Transferencia')
  await expect(list.getByRole('button', { name: /RETIRO CAJERO/ })).not.toContainText(
    /Ingreso|Transferencia/,
  )
})

test.describe('lista compacta', () => {
  const list = (page: Page) => page.getByRole('region', { name: 'Lista de transacciones' })
  const rows = (page: Page) => list(page).locator('button[data-fingerprint]')

  test('las filas son de una línea: caben más en la misma pantalla', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`/transacciones?mes=${MONTH}`)
    await expect(rows(page).first()).toBeVisible()
    const heights = await rows(page).evaluateAll((els) =>
      els.map((el) => el.getBoundingClientRect().height),
    )
    expect(heights.length).toBe(22)
    for (const height of heights) expect(height).toBeLessThanOrEqual(52)
    // El original en US$ va junto al monto en RD$, en la misma línea.
    const row = list(page).getByRole('button', { name: /TIENDA ONLINE/ })
    await expect(row).toContainText(/US\$ 30\.00\s*RD\$ 1,902/)
  })

  test('el detalle y el encabezado del día siguen a la vista al desplazarse', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 700 })
    await page.goto(`/transacciones?mes=${MONTH}`)
    // Un día con dos filas, lejos del final para que la página pueda subirlo hasta arriba.
    const day = list(page).getByRole('group', { name: 'Martes 20 de enero' })
    await day.evaluate((el) => {
      el.scrollIntoView({ block: 'start' })
      window.scrollBy(0, 30)
    })
    const header = await day.locator('[data-day-header]').boundingBox()
    expect(Math.abs(header!.y)).toBeLessThanOrEqual(1)

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await list(page).getByRole('button', { name: /CAFE FICTICIO/ }).click()
    const detail = page.getByRole('complementary')
    await expect(detail.getByRole('heading', { name: /CAFE FICTICIO/ })).toBeInViewport()
    const box = await detail.boundingBox()
    expect(box!.y).toBeGreaterThanOrEqual(0)
    expect(box!.y).toBeLessThan(700)
  })

  test('agrupar por categoría: grupos cerrados con su total; al abrir salen las filas', async ({
    page,
  }) => {
    await page.goto(`/transacciones?mes=${MONTH}`)
    await page.getByRole('search').getByLabel('Agrupar por').selectOption('Categoría')
    await expect(page).toHaveURL(/agrupar=categoria/)

    const toggles = list(page).getByRole('button', { expanded: false })
    await expect(toggles.first()).toBeVisible()
    await expect(rows(page)).toHaveCount(0)
    // La categoría con más gasto va primero: Otros, 4 compras.
    await expect(toggles.first()).toHaveText(/^Otros\s*4 transacciones · RD\$ 6,600$/)

    await toggles.first().click()
    const otros = list(page).getByRole('button', { name: /^Otros \d+ transacci/ })
    await expect(otros).toHaveAttribute('aria-expanded', 'true')
    await expect(rows(page)).toHaveCount(4)
    for (const row of await rows(page).all()) await expect(row).toContainText('Otros')

    await otros.press('Enter')
    await expect(otros).toHaveAttribute('aria-expanded', 'false')
    await expect(rows(page)).toHaveCount(0)
  })

  test('ordenar por monto: dentro de cada día, el mayor primero', async ({ page }) => {
    await page.goto(`/transacciones?mes=${MONTH}`)
    await page.getByRole('search').getByLabel('Ordenar').selectOption('Monto (mayor primero)')
    await expect(page).toHaveURL(/orden=monto/)
    const day = list(page).getByRole('group', { name: 'Lunes 5 de enero' })
    const names = await day.locator('button[data-fingerprint]').allInnerTexts()
    expect(names.map((n) => n.split('\n')[0])).toEqual([
      'SU PAGO',
      'TRANSFERENCIA RECIBIDA',
      'TIENDA ONLINE',
      'STREAMING FICTICIO',
    ])
  })

  test('agrupar por comercio y ordenar por monto viven en la URL', async ({ page }) => {
    await page.goto(`/transacciones?mes=${MONTH}&agrupar=comercio&orden=monto`)
    await expect(page.getByRole('search').getByLabel('Agrupar por')).toHaveValue('merchant')
    await expect(page.getByRole('search').getByLabel('Ordenar')).toHaveValue('amount')
    const pagos = list(page).getByRole('button', { name: /^SU PAGO/ })
    await expect(pagos).toHaveAttribute('aria-expanded', 'false')
    await pagos.click()
    await expect(rows(page)).toHaveCount(2)
  })

  test('en 390 px: dos líneas por fila y sin desplazamiento a los lados', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const route of [
      `/transacciones?mes=${MONTH}`,
      `/transacciones?mes=${MONTH}&agrupar=categoria&orden=monto`,
    ]) {
      await page.goto(route)
      const toggle = list(page).getByRole('button', { expanded: false }).first()
      if (route.includes('agrupar')) await toggle.click()
      await expect(rows(page).first()).toBeVisible()
      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width, route).toBeLessThanOrEqual(390)
      for (const height of await rows(page).evaluateAll((els) =>
        els.map((el) => el.getBoundingClientRect().height),
      ))
        expect(height, route).toBeLessThanOrEqual(64)
    }
  })
})

test('cuentas: elegir otra tarjeta cambia el encabezado del panel', async ({ page }) => {
  await page.goto('/cuentas')
  const heading = page.getByRole('region', { name: /···/ }).getByRole('heading', { level: 2 })
  const before = await heading.innerText()

  const other = before.includes('VISA DEMO') ? 'MC BLACK' : 'VISA DEMO'
  await page.getByRole('button', { name: new RegExp(other) }).click()

  await expect(heading).toContainText(other)
  await expect(page).toHaveURL(/cuenta=/)
})

test('cuentas: la tabla de estados cabe sin desplazamiento horizontal en 1232 px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1232, height: 961 })
  // La tarjeta con intereses lleva el veredicto bajo el saldo: también debe caber.
  for (const route of ['/cuentas', INTEREST_CARD_PAGE]) {
    await page.goto(route)
    const box = page.getByRole('region', { name: 'Estados' })
    await expect(box).toBeVisible()
    const overflow = await box.evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(overflow, route).toBeLessThanOrEqual(0)
  }
})

test.describe('intereses', () => {
  test('cuentas: franja de pago y lo que quedó del corte de diciembre', async ({ page }) => {
    // La fecha límite inventada (22 feb 2026) ya pasó: la franja dice que venció.
    await page.goto(INTEREST_CARD_PAGE)
    const panel = page.getByRole('region', { name: /MASTERCARD FICTICIA/ })
    await expect(panel).toContainText('Para no pagar intereses: RD$ 7,637 · venció el 22 feb')
    await expect(panel).toContainText('Mínimo: RD$ 380')
    const table = page.getByRole('region', { name: 'Estados' })
    await expect(table.getByRole('row').filter({ hasText: '28 dic' })).toContainText(
      /Quedó RD\$ 6,150\s*\+RD\$ 287 de intereses/,
    )
    await expect(table.getByRole('row').filter({ hasText: '28 nov' })).toContainText('Completo')
    await expect(page.getByRole('button', { name: /MASTERCARD FICTICIA/ })).toContainText(
      'RD$ 7,637 · venció el 22 feb',
    )
  })

  test('cuentas: antes de la fecha límite la franja dice "antes del"', async ({ page }) => {
    // La pantalla compara con la fecha del navegador.
    await page.clock.setFixedTime(new Date('2026-02-15T12:00:00'))
    await page.goto(INTEREST_CARD_PAGE)
    await expect(page.getByRole('region', { name: /MASTERCARD FICTICIA/ })).toContainText(
      'Para no pagar intereses: RD$ 7,637 antes del 22 feb',
    )
  })

  test('resumen: intereses del año y el próximo pago lleva a Cuentas', async ({ page }) => {
    // El servidor solo da el próximo pago si vence de hoy en adelante; las fechas inventadas
    // ya pasaron, así que se agrega aquí sobre la respuesta real.
    await page.route('**/api/interest**', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: {
          ...body,
          next_due: {
            key: 'ficticio:credit_card',
            label: 'MASTERCARD FICTICIA ···5151',
            due_date: '2026-02-22',
            amounts: [{ currency: 'DOP', cents: 763740 }],
            minimums: [{ currency: 'DOP', cents: 38000 }],
            text: '',
          },
        },
      })
    })
    await page.goto(`/?mes=${MONTH}`)
    const card = page.getByRole('region', { name: 'Tarjetas' })
    await expect(card).toContainText('Intereses 2026')
    await expect(card).toContainText('RD$ 287')
    await expect(card).toContainText('MASTERCARD FICTICIA ···5151')

    await card.getByRole('link', { name: /Próximo: paga RD\$ 7,637 antes del 22 feb/ }).click()
    await expect(page).toHaveURL(/\/cuentas\?cuenta=ficticio%3Acredit_card$/)
    await expect(
      page.getByRole('region', { name: /···/ }).getByRole('heading', { level: 2 }),
    ).toContainText('MASTERCARD FICTICIA')
  })

  test('resumen: un año sin intereses lo dice', async ({ page }) => {
    await page.goto('/?mes=2025-12')
    const card = page.getByRole('region', { name: 'Tarjetas' })
    await expect(card).toContainText('Intereses 2025')
    await expect(card).toContainText('Sin intereses este año')
  })
})

test.describe('recurrentes', () => {
  test.describe.configure({ mode: 'serial' })

  test('lista los recurrentes; "No es recurrente" lo descarta y "Deshacer" lo devuelve', async ({
    page,
  }) => {
    await page.goto('/recurrentes')
    await expect(page.getByRole('heading', { level: 1, name: 'Recurrentes' })).toBeVisible()
    const streaming = page.getByRole('listitem').filter({ hasText: 'STREAMING FICTICIO' })
    await expect(streaming).toContainText('Subió')
    await expect(page.getByRole('listitem').filter({ hasText: 'GIMNASIO FICTICIO' })).toBeVisible()

    await page.getByRole('button', { name: 'Marcar GIMNASIO FICTICIO' }).click()
    await page
      .getByRole('group', { name: 'Marcas de GIMNASIO FICTICIO' })
      .getByRole('button', { name: 'No es recurrente' })
      .click()

    const dismissed = page.getByRole('region', { name: 'Descartados' })
    await dismissed.getByRole('button', { name: 'Descartados (1)' }).click()
    await expect(dismissed).toContainText('GIMNASIO FICTICIO')
    await expect(page.getByRole('button', { name: 'Marcar GIMNASIO FICTICIO' })).toHaveCount(0)

    await dismissed.getByRole('button', { name: 'Deshacer: GIMNASIO FICTICIO' }).click()
    await expect(page.getByRole('button', { name: 'Marcar GIMNASIO FICTICIO' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Descartados' })).toHaveCount(0)
  })

  test('resumen de febrero 2026: la tarjeta avisa la subida y lleva a Recurrentes', async ({
    page,
  }) => {
    await page.goto('/?mes=2026-02')
    const card = page.getByRole('region', { name: 'Recurrentes' })
    await expect(card).toContainText('Subió de US$ 9.99 a US$ 11.99')
    await card.getByRole('link', { name: 'Ver todos' }).click()
    await expect(page).toHaveURL(/\/recurrentes$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Recurrentes' })).toBeVisible()
  })
})

test.describe('gastos únicos sugeridos (en «Para revisar»)', () => {
  test.describe.configure({ mode: 'serial' })
  // Febrero 2026 trae una compra grande y rara inventada (AGENCIA FICTICIA, RD$ 45,000).
  const FEBRUARY = '2026-02'
  const card = (page: Page) => page.getByRole('region', { name: /Para revisar/ })

  test('transacciones: la fila sugerida lleva «¿Único?» y el detalle dice por qué', async ({
    page,
  }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    await expect(list.getByRole('button', { name: /AGENCIA FICTICIA/ })).toContainText('¿Único?')
    await expect(list.getByRole('button', { name: /CINE INVENTADO/ })).not.toContainText('Único')

    await list.getByRole('button', { name: /AGENCIA FICTICIA/ }).click()
    const detail = page.getByRole('complementary')
    await expect(detail).toContainText('comercio nuevo')
    await expect(detail.getByRole('button', { name: 'No es único' })).toBeVisible()
  })

  test('resumen: la tarjeta cabe en 390 px', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/?mes=${FEBRUARY}`)
    await expect(card(page)).toContainText(/Para revisar \(\d+\)/)
    await expect(card(page)).toContainText('¿Gasto único?')
    await expect(card(page)).toContainText('RD$ 45,000')
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width).toBeLessThanOrEqual(390)
  })

  test('resumen: en 390 px el nombre va en una línea; día y cuenta debajo', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/?mes=${FEBRUARY}`)
    const link = card(page).getByRole('link', { name: /Ver en Transacciones: AGENCIA FICTICIA/ })
    await expect(card(page)).toContainText('6 feb · VISA DEMO ···4242')
    const name = link.getByTitle(/AGENCIA FICTICIA/)
    const lines = await name.evaluate((el) => {
      const style = getComputedStyle(el)
      return Math.round(el.getBoundingClientRect().height / parseFloat(style.lineHeight))
    })
    expect(lines).toBe(1)
  })

  test('resumen: la sugerencia abre la compra en Transacciones; Atrás vuelve', async ({ page }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    await card(page)
      .getByRole('link', { name: /Ver en Transacciones: AGENCIA FICTICIA/ })
      .click()
    await expect(page).toHaveURL(new RegExp(`/transacciones\\?mes=${FEBRUARY}&tx=`))
    const detail = page.getByRole('complementary')
    await expect(detail.getByRole('heading', { name: /AGENCIA FICTICIA/ })).toBeVisible()
    await expect(detail).toContainText('comercio nuevo')

    await page.goBack()
    await expect(page).toHaveURL(new RegExp(`/\\?mes=${FEBRUARY}$`))
    await expect(card(page)).toContainText('AGENCIA FICTICIA')
  })

  test('resumen: «No es único» la quita; «Volver a sugerir» la devuelve', async ({ page }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    await expect(card(page)).toContainText('AGENCIA FICTICIA')
    await card(page).getByRole('button', { name: 'No es único: AGENCIA FICTICIA' }).click()
    await expect(card(page)).not.toContainText('AGENCIA FICTICIA')
    // El botón no es parte del enlace: no sale del Resumen.
    await expect(page).toHaveURL(new RegExp(`/\\?mes=${FEBRUARY}$`))

    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    const row = list.getByRole('button', { name: /AGENCIA FICTICIA/ })
    await expect(row).not.toContainText('Único')
    await row.click()
    const detail = page.getByRole('complementary')
    await detail.getByRole('button', { name: 'Volver a sugerir' }).click()
    await expect(row).toContainText('¿Único?')
    await expect(detail.getByRole('button', { name: 'No es único' })).toBeVisible()
  })

  test('resumen: «Es único» la pasa a «Gastos únicos»', async ({ page }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    const kpis = page.getByRole('region', { name: 'Indicadores' })
    await expect(kpis).toContainText(/Gastos únicos\s*RD\$\s*0/)
    await card(page).getByRole('button', { name: 'Es único: AGENCIA FICTICIA', exact: true }).click()
    await expect(card(page)).not.toContainText('AGENCIA FICTICIA')
    await expect(page).toHaveURL(new RegExp(`/\\?mes=${FEBRUARY}$`))
    await expect(kpis).toContainText(/Gastos únicos\s*RD\$\s*45,000/)
  })
})

test.describe('para revisar', () => {
  test.describe.configure({ mode: 'serial' })
  const FEBRUARY = '2026-02'
  const card = (page: Page) => page.getByRole('region', { name: /Para revisar/ })

  test('resumen: junta ingresos inusuales, transferencias grandes y subidas de precio', async ({
    page,
  }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    await expect(card(page)).toContainText('Ingreso inusual')
    await expect(card(page)).toContainText('DEPOSITO CAMBIO FICTICIO')
    await expect(card(page)).toContainText('Transferencia grande')
    await expect(card(page)).toContainText('RD$ 63,700')
    await expect(card(page)).toContainText('US$ 1,000.00')
    await expect(card(page)).toContainText('Subió de US$ 9.99 a US$ 11.99')
    await expect(card(page)).not.toContainText('Posibles gastos únicos')
  })

  test('resumen: con solo la VISA quedan los de la tarjeta', async ({ page }) => {
    await page.goto(`/?mes=${FEBRUARY}&cuentas=demo%3Acredit_card`)
    await expect(card(page)).toContainText('STREAMING FICTICIO')
    await expect(card(page)).not.toContainText('DEPOSITO CAMBIO FICTICIO')
  })

  test('resumen: «✓ Revisado» lo quita y no vuelve al recargar', async ({ page }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    await card(page).getByRole('button', { name: 'Revisado: STREAMING FICTICIO' }).click()
    await expect(card(page)).not.toContainText('STREAMING FICTICIO')
    await page.reload()
    await expect(card(page)).toContainText('DEPOSITO CAMBIO FICTICIO')
    await expect(card(page)).not.toContainText('STREAMING FICTICIO')
  })

  test('resumen: el movimiento abre su detalle en Transacciones', async ({ page }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    await card(page).getByRole('link', { name: /Ver en Transacciones: DEPOSITO CAMBIO FICTICIO/ }).click()
    await expect(page).toHaveURL(new RegExp(`/transacciones\\?mes=${FEBRUARY}&tx=`))
    await expect(page.getByRole('complementary').getByRole('heading', { name: /DEPOSITO CAMBIO/ })).toBeVisible()
  })
})

test('cuentas bancarias con nombre corto en Transacciones y en «Por cuenta»', async ({ page }) => {
  // La cuenta corriente inventada se guarda como "FICTICIO Cuenta corriente 777-0".
  const FULL = 'FICTICIO Cuenta corriente 777-0'
  await page.goto('/transacciones?mes=2026-01')
  const row = page
    .getByRole('region', { name: 'Lista de transacciones' })
    .getByRole('button', { name: /RETIRO CAJERO/ })
  await expect(row).toContainText(/Corriente\s*···7770/)
  await expect(row).not.toContainText(FULL)
  await expect(row.getByTitle(FULL).first()).toBeAttached()

  await page.goto('/?mes=2026-01')
  const byAccount = page.getByRole('region', { name: 'Por cuenta' })
  await expect(byAccount.getByRole('link', { name: /Corriente ···7770/ })).toHaveAttribute(
    'title',
    FULL,
  )
})

test.describe('teléfono', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  for (const route of [
    '/',
    `/?mes=${MONTH}`,
    '/?mes=2026-02',
    '/transacciones',
    `/transacciones?mes=${MONTH}&tipo=ingresos`,
    '/recurrentes',
    '/cuentas',
    '/categorias',
    INTEREST_CARD_PAGE,
  ]) {
    test(`${route}: la barra va arriba y la página no se desplaza a los lados`, async ({
      page,
    }) => {
      await page.goto(route)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

      const nav = await page.getByRole('navigation', { name: 'Principal' }).boundingBox()
      const main = await page.getByRole('main').boundingBox()
      expect(nav).not.toBeNull()
      expect(main).not.toBeNull()
      expect(nav!.y + nav!.height).toBeLessThanOrEqual(main!.y + 1)

      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width).toBeLessThanOrEqual(390)
    })
  }
})

test.describe('cuentas elegidas', () => {
  const VISA = 'VISA DEMO ···4242'

  async function openPicker(page: Page) {
    await page.getByRole('button', { name: /^Elegir cuentas/ }).click()
    return page.getByRole('dialog')
  }

  test('una tarjeta: cambian los indicadores y Transacciones muestra solo esa tarjeta', async ({
    page,
  }) => {
    await page.goto(`/?mes=${MONTH}`)
    const kpis = page.getByRole('region', { name: 'Indicadores' })
    await expect(kpis).toContainText(/Gastos\s*RD\$\s*18,573/)

    // Desde "Todas", dejar solo la VISA DEMO: se desmarcan las demás.
    const dialog = await openPicker(page)
    for (const box of await dialog.getByRole('checkbox').all()) {
      const label = await box.evaluate((el) => el.closest('label')?.textContent ?? '')
      if (label.includes(VISA)) continue
      await box.click()
      await expect(box).not.toBeChecked()
    }
    // La última no se quita, y lo dice.
    await expect(dialog.getByRole('checkbox', { name: VISA })).toBeDisabled()
    await expect(dialog.getByRole('checkbox', { name: VISA })).toHaveAccessibleDescription(
      'Siempre queda al menos una cuenta',
    )
    await page.keyboard.press('Escape')

    await expect(page).toHaveURL(/cuentas=demo%3Acredit_card/)
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(VISA)
    await expect(page.getByText(`en ${VISA} · montos en RD$`)).toBeVisible()
    await expect(kpis).not.toContainText(/Gastos\s*RD\$\s*18,573/)
    await expect(kpis).toContainText(/Te quedó\s*—/)
    await expect(kpis).toContainText('Elige una cuenta con ingresos para ver el flujo')
    const byAccount = page.getByRole('region', { name: 'Por cuenta' }).getByRole('link')
    await expect(byAccount).toHaveCount(1)
    await expect(byAccount).toContainText(VISA)

    await page.getByRole('region', { name: 'Categorías' }).getByRole('link').first().click()
    await expect(page).toHaveURL(/cuentas=demo%3Acredit_card/)
    const rows = page.getByRole('region', { name: 'Lista de transacciones' }).getByRole('button')
    await expect(rows.first()).toBeVisible()
    for (const row of await rows.all()) await expect(row).toContainText(/VISA DEMO\s*···4242/)

    // Se recuerda: el Resumen sin parámetros sigue con la VISA; "Todas" lo quita.
    await page.goto('/')
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(VISA)
    await (await openPicker(page)).getByRole('button', { name: 'Todas' }).click()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(
      'Cuentas: Todas',
    )
    await page.reload()
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(
      'Cuentas: Todas',
    )
  })

  test('solo cuentas bancarias: sin intereses y con la línea de lo pagado a tus tarjetas', async ({
    page,
  }) => {
    await page.goto(`/?mes=${MONTH}`)
    await expect(page.getByRole('region', { name: 'Tarjetas' })).toBeVisible()
    await page.getByRole('button', { name: /^Elegir cuentas/ }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Solo cuentas bancarias' }).click()
    await page.keyboard.press('Escape')

    // La corriente, la de ahorro del seed y la de ahorro de los cambios pendientes (de 8 con la
    // caja fuerte, que no es una cuenta bancaria).
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(
      'Cuentas: 3 de 8',
    )
    const kpis = page.getByRole('region', { name: 'Indicadores' })
    await expect(kpis).toContainText(/Pagos a tus tarjetas\s*RD\$\s*11,000/)
    await expect(page.getByRole('region', { name: 'Tarjetas' })).toHaveCount(0)
    // Cajero y préstamo de la cuenta corriente; el pago de la tarjeta no es gasto. (Los
    // ingresos no se miran: otra prueba corrige un depósito en la misma base.)
    await expect(kpis).toContainText(/Gastos\s*RD\$\s*7,000/)
  })

  test('un enlace viejo con ?cuenta= sigue filtrando Transacciones', async ({ page }) => {
    await page.goto(`/transacciones?mes=${MONTH}&cuenta=ficticio%3Achecking%3A777-0`)
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(
      'Corriente ···7770',
    )
    const rows = page.getByRole('region', { name: 'Lista de transacciones' }).getByRole('button')
    await expect(rows.first()).toBeVisible()
    for (const row of await rows.all()) await expect(row).toContainText('···7770')
  })

  test('en 390 px el selector abierto no desplaza la página a los lados', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const route of [`/?mes=${MONTH}`, `/transacciones?mes=${MONTH}`]) {
      await page.goto(route)
      await page.getByRole('button', { name: /^Elegir cuentas/ }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width, route).toBeLessThanOrEqual(390)
      const box = await page.getByRole('dialog').boundingBox()
      expect(box!.x, route).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width, route).toBeLessThanOrEqual(390)
      await page.keyboard.press('Escape')
    }
  })

  test('una selección que llega por la URL se recuerda: el menú lleva a Transacciones con ella', async ({
    page,
  }) => {
    await page.goto(`/?mes=${MONTH}&cuentas=demo%3Acredit_card`)
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(VISA)
    await page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name: 'Transacciones' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Transacciones' })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(VISA)
  })

  test('Recurrentes: «Ver todos» lleva las cuentas y la pantalla usa el mismo selector', async ({
    page,
  }) => {
    await page.goto('/recurrentes')
    const all = await page.locator('main header').first().innerText()
    await page.goto(`/?mes=${MONTH}&cuentas=demo%3Acredit_card`)
    await page.getByRole('region', { name: 'Recurrentes' }).getByRole('link', { name: 'Ver todos' }).click()
    await expect(page).toHaveURL(/\/recurrentes\?cuentas=demo%3Acredit_card/)
    await expect(page.getByRole('button', { name: /^Elegir cuentas/ })).toContainText(VISA)
    await expect(page.getByText('STREAMING FICTICIO').first()).toBeVisible()
    await expect(page.locator('main header').first()).not.toHaveText(all)
  })
})

test.describe('categorías editables', () => {
  test.describe.configure({ mode: 'serial' })
  const FEBRUARY = '2026-02'

  test('crear «Mantenimiento del vehículo» con la palabra TALLER mueve la compra del taller', async ({
    page,
  }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await expect(page.getByRole('button', { name: /TALLER FICTICIO/ })).toContainText('Otros')

    await page.getByRole('link', { name: 'Categorías' }).click()
    await page.getByRole('button', { name: 'Nueva categoría' }).click()
    const create = page.getByRole('dialog', { name: 'Nueva categoría' })
    await create.getByLabel('Nombre').fill('Mantenimiento del vehículo')
    await create.getByRole('button', { name: 'Crear' }).click()
    await expect(create).toBeHidden()

    const row = page.getByRole('listitem', { name: 'Mantenimiento del vehículo' })
    await expect(row).toContainText('Sin transacciones este año')
    await expect(row.getByTitle(/Color automático/)).toBeVisible()
    await row
      .getByRole('button', { name: 'Palabras clave de Mantenimiento del vehículo', exact: true })
      .click()
    const words = page.getByRole('dialog', { name: /Palabras clave/ })
    await words.getByLabel(/Palabras o frases/).fill('taller')
    await expect(words.getByRole('status')).toContainText('Esto moverá 1 transacción (RD$ 1,500)')
    await words.getByRole('button', { name: 'Guardar' }).click()
    await expect(words).toBeHidden()
    await expect(row).toContainText('Palabras: TALLER')

    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await expect(page.getByRole('button', { name: /TALLER FICTICIO/ })).toContainText(
      'Mantenimiento del vehículo',
    )
  })

  test('«+ Nueva categoría…» en el detalle la crea y la deja elegida', async ({ page }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await page.getByRole('button', { name: /CINE INVENTADO/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel('Categoría').selectOption('+ Nueva categoría…')
    const create = page.getByRole('dialog', { name: 'Nueva categoría' })
    await expect(create.getByLabel('Tipo')).toHaveValue('gasto') // el tipo de la fila
    await create.getByLabel('Nombre').fill('Cine y teatro')
    await create.getByRole('button', { name: 'Crear' }).click()
    await expect(create).toBeHidden()

    await expect(detail.getByLabel('Categoría')).toHaveValue('Cine y teatro')
    await detail.getByRole('button', { name: 'Guardar' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Guardado' })).toBeVisible()
    await expect(page.getByRole('button', { name: /CINE INVENTADO/ })).toContainText(
      'Cine y teatro',
    )
  })

  test('una categoría oculta no se ofrece al corregir', async ({ page }) => {
    await page.goto('/categorias')
    const row = page.getByRole('listitem', { name: 'Cine y teatro' })
    await row.getByRole('button', { name: 'Ocultar Cine y teatro', exact: true }).click()
    await expect(row).toContainText('Oculta')
    await expect(row.getByRole('button', { name: 'Mostrar Cine y teatro', exact: true })).toBeVisible()

    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await page.getByRole('button', { name: /TALLER FICTICIO/ }).click()
    const select = page.getByRole('complementary').getByLabel('Categoría')
    await expect(select.locator('option[value="Cine y teatro"]')).toHaveCount(0)
    await expect(select.locator('option[value="Mantenimiento del vehículo"]')).toHaveCount(1)
  })
})

test.describe('compartidos, reembolsos y notas', () => {
  test.describe.configure({ mode: 'serial' })
  // Febrero 2026: una cena de RD$ 3,000 en la VISA DEMO y dos TOKE DE (RD$ 1,000 el 4 y RD$ 500
  // el 6).
  const FEBRUARY = '2026-02'

  test('«Compartir…» abre la pantalla; «Éramos 3» deja tu parte y «Volver» elige la fila', async ({
    page,
  }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    const dinner = list.getByRole('button', { name: /RESTAURANTE COMPARTIDO/ })
    await dinner.click()
    const detail = page.getByRole('complementary')
    await detail.getByRole('button', { name: 'Compartir…' }).click()

    await expect(page).toHaveURL(/\/transacciones\/[^/?]+$/)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/RESTAURANTE COMPARTIDO/)
    // El foco va al título (anuncia la pantalla) y las secciones cuelgan de él (h2).
    await expect(page.getByRole('heading', { level: 1 })).toBeFocused()
    await expect(page.getByRole('heading', { level: 2, name: 'Compartir' })).toBeVisible()
    await page.getByLabel('Cuántos eran').fill('3')
    await page.getByRole('button', { name: 'Marcar compartido' }).click()
    await expect(page.getByRole('heading', { level: 2, name: 'Compartido · 1 gasto' })).toBeVisible()
    await expect(page.getByTestId('shared-line')).toHaveText(
      'Tu parteRD$ 1,000DevueltoRD$ 0Te debenRD$ 2,000',
    )

    await page.getByRole('link', { name: 'Volver' }).click()
    await expect(page).toHaveURL(new RegExp(`/transacciones\\?mes=${FEBRUARY}&tx=`))
    await expect(dinner).toHaveAttribute('aria-pressed', 'true')
    await expect(dinner).toContainText('Compartido')
    await expect(dinner).toContainText('te deben RD$ 2,000')
    await expect(dinner).toContainText('de RD$ 3,000')
    await expect(detail.getByTestId('link-summary-shared')).toHaveText(
      /^Parte de RESTAURANTE COMPARTIDO.* · te deben RD\$ 2,000 · 0 reembolsos$/,
    )
  })

  test('el atajo del panel enlaza el TOKE DE sugerido', async ({ page }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    const toke = list.getByRole('button', { name: /TOKE DE PERSONA/ })
    await expect(toke).toContainText('¿Reembolso?')
    await toke.click()
    const detail = page.getByRole('complementary')
    await expect(detail).toContainText(/¿Reembolso de RESTAURANTE COMPARTIDO[^?]*\?/)
    await detail.getByRole('button', { name: 'Sí, enlazar' }).click()
    await expect(toke).toContainText('Reembolso')
    await expect(toke).not.toContainText('¿Reembolso?')
    await expect(detail.getByTestId('link-summary-reimbursement')).toHaveText(
      /^Es reembolso de RESTAURANTE COMPARTIDO.* · te deben RD\$ 1,000$/,
    )
    const dinner = list.getByRole('button', { name: /RESTAURANTE COMPARTIDO/ })
    await expect(dinner).toContainText('te deben RD$ 1,000')
  })

  test('«Gestionar…» enlaza otro reembolso desde la pantalla, con el buscador', async ({ page }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await page.getByRole('button', { name: /RESTAURANTE COMPARTIDO/ }).click()
    await page.getByRole('complementary').getByRole('button', { name: 'Gestionar…' }).click()
    await page.getByRole('button', { name: 'Agregar reembolso' }).click()

    const credits = page.getByRole('group', { name: 'Créditos que pueden ser el reembolso' })
    await expect(credits).toContainText('TOKE DE AMIGA INVENTADA')
    await page.getByRole('searchbox', { name: /Buscar en créditos/ }).fill('500')
    await expect(credits.getByRole('checkbox')).toHaveCount(1)
    await credits.getByRole('checkbox', { name: /TOKE DE AMIGA/ }).check()
    await page.getByRole('button', { name: 'Enlazar crédito' }).click()
    await expect(page.getByTestId('shared-line')).toHaveText(
      'Tu parteRD$ 1,000DevueltoRD$ 1,500Te debenRD$ 500',
    )
    await expect(page.getByRole('list', { name: 'Reembolsos' })).toContainText('TOKE DE AMIGA')
  })

  test('Pendientes lista lo que te deben; Transacciones filtra los compartidos con pendiente', async ({
    page,
  }) => {
    await page.goto(`/?mes=${FEBRUARY}`)
    // El widget del Resumen suma todos los meses (con los pendientes inventados de diciembre).
    const widget = page.getByRole('region', { name: 'Pendientes' })
    await widget.getByRole('link', { name: 'Ver pendientes' }).click()
    await expect(page).toHaveURL(/\/pendientes$/)
    const owed = page.getByRole('region', { name: 'Te deben' })
    await expect(owed.getByRole('link', { name: /RESTAURANTE COMPARTIDO/ })).toContainText('RD$ 500')

    await page.goto(`/transacciones?mes=${FEBRUARY}&compartidos=pendientes`)
    const rows = page.getByRole('region', { name: 'Lista de transacciones' }).getByRole('button')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText('RESTAURANTE COMPARTIDO')
    await page.getByRole('button', { name: 'Quitar el filtro de compartidos con pendiente' }).click()
    await expect(page).not.toHaveURL(/compartidos=/)
  })

  test('una nota se guarda, se marca en la fila y la búsqueda la encuentra', async ({ page }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    await list.getByRole('button', { name: /RESTAURANTE COMPARTIDO/ }).click()
    const detail = page.getByRole('complementary')
    await detail.getByLabel('Nota').fill('Cena con Ana y Luis')
    await detail.getByRole('button', { name: 'Guardar', exact: true }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Guardado' })).toBeVisible()
    const dinner = list.getByRole('button', { name: /RESTAURANTE COMPARTIDO/ })
    await expect(dinner.getByRole('img', { name: 'Tiene nota' })).toBeVisible()

    await page.goto(`/transacciones?mes=${FEBRUARY}&q=luis`)
    await expect(list.getByRole('button')).toHaveCount(1)
    await expect(list.getByRole('button').first()).toContainText('RESTAURANTE COMPARTIDO')
  })

  test('en 390 px la pantalla del compartido cabe sin desplazar a los lados', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await page.getByRole('button', { name: /RESTAURANTE COMPARTIDO/ }).click()
    await page.getByRole('complementary').getByRole('button', { name: 'Gestionar…' }).click()
    await expect(page.getByTestId('shared-line')).toBeVisible()
    await page.getByRole('button', { name: 'Agregar reembolso' }).click()
    await page.getByRole('button', { name: 'Me pagaron en efectivo o en otra cuenta' }).click()
    await expect(page.getByLabel('Dónde')).toBeVisible()
    const width = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(width).toBeLessThanOrEqual(390)
  })
})

test.describe('cambios de divisas', () => {
  test.describe.configure({ mode: 'serial' })
  // Febrero 2026: un depósito de RD$ 63,700 el 12, un envío de US$ 1,000 el 13 (tasa 63.70) y
  // otro de US$ 61.67 el 14.
  const FEBRUARY = '2026-02'

  async function openDeposit(page: Page) {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    await page.getByRole('button', { name: /DEPOSITO CAMBIO/ }).click()
    await page
      .getByRole('complementary')
      .getByRole('region', { name: 'Cambio de divisas' })
      .getByRole('button', { name: 'Gestionar…' })
      .click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/DEPOSITO CAMBIO/)
  }

  test('la sugerencia vincula el depósito y el envío; la tasa acordada deja pendiente', async ({
    page,
  }) => {
    await page.goto(`/transacciones?mes=${FEBRUARY}`)
    const list = page.getByRole('region', { name: 'Lista de transacciones' })
    const deposit = list.getByRole('button', { name: /DEPOSITO CAMBIO/ })
    await expect(deposit).toContainText('¿Cambio?')
    await deposit.click()
    const detail = page.getByRole('complementary')
    await expect(detail).toContainText(
      '¿Es un cambio de divisas con TRANSFERENCIA A PERSONA FICTICIA (13 de febrero)?',
    )
    await detail.getByRole('button', { name: 'Sí, vincular' }).click()
    await expect(detail.getByTestId('link-summary-exchange')).toHaveText('Cambio: sin pendiente')
    await expect(detail.getByLabel('Categoría')).toBeDisabled()
    await expect(detail).toContainText('Su categoría la define el vínculo')
    await expect(deposit).toContainText('Cambio de divisas')
    await expect(list.getByRole('button', { name: /TRANSFERENCIA A PERSONA/ })).toContainText(
      'Cambio',
    )

    await openDeposit(page)
    await expect(page.getByTestId('exchange-line')).toHaveText(
      'Cambio: RD$ 63,700 ↔ US$ 1,000.00 · tasa 63.70 · sin pendiente',
    )
    await expect(page.getByText('Pon la tasa acordada para ver lo pendiente.')).toBeVisible()
    await page.getByLabel('Tasa acordada', { exact: true }).fill('60')
    await page.getByRole('button', { name: 'Guardar tasa' }).click()
    await expect(page.getByTestId('exchange-line')).toHaveText(
      'Cambio: RD$ 63,700 ↔ US$ 1,000.00 · tasa 60.00 · pendiente US$ 61.67 ≈ RD$ 3,700',
    )

    // Te depositaron primero: lo debes, a la tasa acordada.
    await page.goto('/pendientes')
    const owed = page.getByRole('region', { name: 'Debes' }).getByRole('link', {
      name: /DEPOSITO CAMBIO/,
    })
    await expect(owed).toContainText('US$ 61.67')
    await expect(owed).toContainText('≈ RD$ 3,700 a 60.00')
  })

  test('agregar una pata desde la pantalla: solo lo que cabe en lo pendiente', async ({ page }) => {
    await openDeposit(page)
    const legs = page.getByRole('group', { name: 'Patas posibles' })
    // Falta enviar US$ 61.67: ni los TOKE DE en pesos ni nada más grande se ofrece.
    await expect(legs.getByRole('checkbox')).toHaveCount(1)
    await legs.getByRole('checkbox', { name: /TRANSFERENCIA SALDO PERSONA/ }).check()
    await page.getByRole('button', { name: 'Vincular' }).click()
    await expect(page.getByTestId('exchange-line')).toHaveText(
      'Cambio: RD$ 63,700 ↔ US$ 1,061.67 · tasa 60.00 · sin pendiente',
    )
    await expect(page.getByRole('list', { name: 'Patas del cambio' })).toContainText(
      'TRANSFERENCIA SALDO PERSONA',
    )

    await page.getByRole('link', { name: 'Volver' }).click()
    await expect(page).toHaveURL(new RegExp(`/transacciones\\?mes=${FEBRUARY}&tx=`))
    const deposit = page
      .getByRole('region', { name: 'Lista de transacciones' })
      .getByRole('button', { name: /DEPOSITO CAMBIO/ })
    await expect(deposit).toHaveAttribute('aria-pressed', 'true')
    await expect(deposit).toBeInViewport()
  })

  test('«Cambio completo» lo cierra y el pendiente desaparece de Pendientes', async ({ page }) => {
    await openDeposit(page)
    await page.getByRole('button', { name: 'Cambio completo' }).click()
    await expect(page.getByTestId('exchange-line')).toHaveText(/· completo$/)
    await page.goto('/pendientes')
    await expect(page.getByRole('region', { name: 'Debes' })).not.toContainText('DEPOSITO CAMBIO')
  })

  test('una pantalla abierta directo vuelve al mes de la transacción', async ({ page }) => {
    await openDeposit(page)
    const url = page.url()
    await page.goto(url)
    await page.getByRole('link', { name: 'Volver' }).click()
    await expect(page).toHaveURL(new RegExp(`/transacciones\\?mes=${FEBRUARY}&tx=`))
  })
})

test('transacciones: al llegar con una fila elegida, la lista la trae a la vista', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 420 })
  await page.goto('/transacciones?mes=2026-02')
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  const last = list.locator('[data-fingerprint]').last()
  const fingerprint = await last.getAttribute('data-fingerprint')
  await expect(last).not.toBeInViewport()

  await page.goto(`/transacciones?mes=2026-02&tx=${fingerprint}`)
  const row = list.locator(`[data-fingerprint="${fingerprint}"]`)
  await expect(row).toHaveAttribute('aria-pressed', 'true')
  await expect(row).toBeInViewport({ ratio: 1 })
})

test('transacciones: en el teléfono, al cerrar el detalle la fila elegida está a la vista', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 800 })
  await page.goto('/transacciones?mes=2026-02')
  const list = page.getByRole('region', { name: 'Lista de transacciones' })
  const last = list.locator('[data-fingerprint]').last()
  const fingerprint = await last.getAttribute('data-fingerprint')
  await expect(last).not.toBeInViewport()

  await page.goto(`/transacciones?mes=2026-02&tx=${fingerprint}`)
  await page.getByRole('button', { name: 'Cerrar detalle' }).click()
  await expect(page.getByRole('button', { name: 'Cerrar detalle' })).toBeHidden()
  const row = list.locator(`[data-fingerprint="${fingerprint}"]`)
  await expect(row).toBeInViewport({ ratio: 1 })
})
