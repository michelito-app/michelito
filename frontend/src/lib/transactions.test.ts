import { describe, expect, it } from 'vitest'
import type { Tx } from './api'
import {
  amountLines,
  amountTone,
  apiPath,
  clearFilters,
  dayLabel,
  editBody,
  groupByDay,
  hasNarrowing,
  historyText,
  kindBadge,
  merchantScopeNote,
  oneOffBadge,
  outOfView,
  oneOffAction,
  parseFilters,
  toParams,
  originText,
  totalsParts,
  dayGroups,
  fieldGroups,
  groupLine,
  sortItems,
  totalsOf,
} from './transactions'

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f1',
    day: '2026-09-27',
    merchant: 'Café Ficticio',
    description: 'CAFE FICTICIO SRL',
    category: 'Restaurantes',
    category_id: 2,
    kind: 'gasto',
    original_category: 'Supermercado',
    account: 'visa',
    account_label: 'Visa ···1234',
    amount_cents: 198_000,
    currency: 'DOP',
    amount_dop_cents: 198_000,
    one_off: false,
    corrected: false,
    merchant_year_count: 3,
    suggested_one_off: false,
    one_off_reasons: [],
    one_off_dismissed: false,
    note: '',
    link: '',
    gross_cents: null,
    pending_cents: 0,
    shared: null,
    reimbursement_of: null,
    suggested_group: null,
    exchange: null,
    suggested_exchange_with: null,
    can_invest: false,
    can_invest_credit: false,
    investment: null,
    investment_role: '',
    investment_capital_cents: null,
    suggested_investment: null,
    can_store: false,
    can_deposit: false,
    cash_box_role: '',
    cash_box_currency: null,
    cash_box_amount_cents: null,
    cash_entry_id: null,
    link_id: null,
    can_share: false,
    can_reimburse: false,
    can_exchange: false,
    ...overrides,
  }
}

describe('parseFilters', () => {
  it('lee mes, cuenta, categoría, búsqueda y selección de la URL', () => {
    const params = new URLSearchParams(
      'mes=2026-09&cuenta=visa&categoria=Salud&q=farmacia&tx=abc',
    )
    expect(parseFilters(params)).toEqual({
      month: '2026-09',
      accounts: ['visa'],
      category: 'Salud',
      q: 'farmacia',
      tx: 'abc',
      kind: null,
      group: 'day',
      sort: 'date',
      shared: null,
    })
  })

  it('lee un nombre viejo de categoría con el nombre actual', () => {
    const params = new URLSearchParams('mes=2026-09&categoria=Efectivo+y+transferencias')
    expect(parseFilters(params).category).toBe('Efectivo')
  })

  it('trata lo vacío o ausente como sin filtro', () => {
    expect(parseFilters(new URLSearchParams('cuenta=&q=%20%20'))).toEqual({
      month: null,
      accounts: null,
      category: null,
      q: '',
      tx: null,
      kind: null,
      group: 'day',
      sort: 'date',
      shared: null,
    })
  })
})

describe('cuentas en la URL', () => {
  it('lee varias cuentas de `cuentas` y la `cuenta` de antes como una sola', () => {
    expect(parseFilters(new URLSearchParams('cuentas=visa,bhd')).accounts).toEqual(['bhd', 'visa'])
    expect(parseFilters(new URLSearchParams('cuenta=bhd')).accounts).toEqual(['bhd'])
  })

  it('escribe `cuentas` aunque viniera de `cuenta`', () => {
    const params = toParams(parseFilters(new URLSearchParams('mes=2026-09&cuenta=bhd')))
    expect(params.toString()).toBe('mes=2026-09&cuentas=bhd')
  })
})

describe('toParams', () => {
  it('omite los filtros vacíos y conserva el orden mes, cuenta, categoría, q, tx', () => {
    const params = toParams({
      month: '2026-09',
      accounts: null,
      category: 'Salud',
      q: '',
      tx: 'f',
      kind: null,
      group: 'day',
      sort: 'date',
      shared: null,
    })
    expect(params.toString()).toBe('mes=2026-09&categoria=Salud&tx=f')
  })

  it('es el inverso de parseFilters', () => {
    const filters = {
      month: '2026-09',
      accounts: ['bhd', 'visa'],
      category: null,
      q: 'café',
      tx: null,
      kind: 'ingreso' as const,
      group: 'merchant' as const,
      sort: 'amount' as const,
      shared: 'pending' as const,
    }
    expect(parseFilters(toParams(filters))).toEqual(filters)
    expect(toParams(filters).get('compartidos')).toBe('pendientes')
  })
})

describe('clearFilters / hasNarrowing', () => {
  it('quita cuenta, categoría y búsqueda; conserva el mes y la selección', () => {
    const filters = {
      month: '2026-09',
      accounts: ['bhd'],
      category: 'Salud',
      q: 'x',
      tx: 'f',
      kind: 'gasto' as const,
      group: 'category' as const,
      sort: 'amount' as const,
      shared: null,
    }
    expect(clearFilters(filters)).toEqual({
      month: '2026-09',
      accounts: null,
      category: null,
      q: '',
      tx: 'f',
      kind: null,
      group: 'category',
      sort: 'amount',
      shared: null,
    })
    expect(hasNarrowing(filters)).toBe(true)
    expect(hasNarrowing(clearFilters(filters))).toBe(false)
    const onlyShared = { ...clearFilters(filters), shared: 'pending' as const }
    expect(hasNarrowing(onlyShared)).toBe(true)
    expect(clearFilters(onlyShared).shared).toBeNull()
  })
})

describe('apiPath', () => {
  it('arma la consulta a /api/transactions solo con los filtros puestos', () => {
    expect(
      apiPath('2026-09', {
        accounts: null,
        category: 'Vehículo y combustible',
        q: '',
        kind: null,
        shared: null,
      }),
    ).toBe('/api/transactions?month=2026-09&category=Veh%C3%ADculo+y+combustible')
    expect(
      apiPath('2026-09', { accounts: ['visa', 'bhd'], category: null, q: 'café', kind: null, shared: null }),
    ).toBe('/api/transactions?month=2026-09&accounts=visa%2Cbhd&q=caf%C3%A9')
    expect(
      apiPath('2026-09', { accounts: null, category: null, q: '', kind: null, shared: 'pending' }),
    ).toBe('/api/transactions?month=2026-09&shared=pending')
  })
})

describe('dayLabel', () => {
  it('da el día de la semana, el número y el mes en español', () => {
    expect(dayLabel('2026-09-27')).toBe('Domingo 27 de septiembre')
    expect(dayLabel('2026-09-26')).toBe('Sábado 26 de septiembre')
    expect(dayLabel('2026-01-05')).toBe('Lunes 5 de enero')
  })
})

describe('groupByDay', () => {
  it('agrupa filas seguidas del mismo día y conserva el orden', () => {
    const a = tx({ fingerprint: 'a', day: '2026-09-29' })
    const b = tx({ fingerprint: 'b', day: '2026-09-29' })
    const c = tx({ fingerprint: 'c', day: '2026-09-27' })
    expect(groupByDay([a, b, c])).toEqual([
      { day: '2026-09-29', label: 'Martes 29 de septiembre', items: [a, b] },
      { day: '2026-09-27', label: 'Domingo 27 de septiembre', items: [c] },
    ])
    expect(groupByDay([])).toEqual([])
  })
})

describe('editBody', () => {
  const row = tx()
  const unchanged = {
    category: 'Restaurantes',
    oneOff: false,
    scope: 'transaction',
    note: '',
  } as const

  it('no manda nada si no cambió', () => {
    expect(editBody(row, unchanged)).toBeNull()
  })

  it('manda solo la categoría si solo cambió la categoría', () => {
    expect(editBody(row, { ...unchanged, category: 'Salud' })).toEqual({
      category: 'Salud',
      scope: 'transaction',
    })
  })

  it('manda solo el gasto único si solo cambió eso', () => {
    expect(editBody(row, { ...unchanged, oneOff: true })).toEqual({
      one_off: true,
      scope: 'transaction',
    })
  })

  it('manda ambos con el alcance de comercio', () => {
    expect(editBody(row, { category: 'Salud', oneOff: true, scope: 'merchant', note: '' })).toEqual({
      category: 'Salud',
      one_off: true,
      scope: 'merchant',
    })
  })

  it('manda la nota sin espacios de más cuando cambia; vacía la borra', () => {
    expect(editBody(row, { ...unchanged, note: '  con Ana ' })).toEqual({
      note: 'con Ana',
      scope: 'transaction',
    })
    expect(editBody(tx({ note: 'x' }), { ...unchanged, note: '' })).toEqual({
      note: '',
      scope: 'transaction',
    })
    expect(editBody(tx({ note: 'x' }), { ...unchanged, note: ' x ' })).toBeNull()
  })

  it('con alcance de comercio aplica la categoría actual a todo el comercio', () => {
    expect(editBody(row, { ...unchanged, scope: 'merchant' })).toEqual({
      category: 'Restaurantes',
      scope: 'merchant',
    })
  })
})

describe('historyText', () => {
  it('cuenta las compras del comercio en el año de la transacción', () => {
    expect(historyText(tx())).toBe('3 compras en 2026')
    expect(historyText(tx({ merchant_year_count: 1, day: '2025-12-30' }))).toBe('1 compra en 2025')
  })
})

describe('merchantScopeNote', () => {
  it('una compra lleva cuántas hubo en el año', () => {
    expect(merchantScopeNote(tx())).toBe('3 compras en 2026, también a futuro')
  })

  it('un crédito no cuenta compras', () => {
    expect(merchantScopeNote(tx({ amount_cents: -50_000, amount_dop_cents: -50_000 }))).toBe(
      'también a futuro',
    )
  })
})

describe('oneOffBadge', () => {
  it('marca lo único y lo sugerido, y nada más', () => {
    expect(oneOffBadge(tx({ one_off: true }))).toBe('Único')
    expect(oneOffBadge(tx({ suggested_one_off: true, one_off_reasons: ['comercio nuevo'] }))).toBe(
      '¿Único?',
    )
    expect(oneOffBadge(tx({ one_off: true, suggested_one_off: true }))).toBe('Único')
    expect(oneOffBadge(tx())).toBeNull()
  })
})

describe('oneOffAction', () => {
  it('descartar lo sugerido, volver a sugerir lo descartado, nada si ya es único', () => {
    expect(oneOffAction(tx({ suggested_one_off: true, one_off_reasons: ['comercio nuevo'] }))).toBe(
      'dismiss',
    )
    expect(oneOffAction(tx({ one_off_dismissed: true }))).toBe('restore')
    expect(oneOffAction(tx({ one_off: true, one_off_dismissed: true }))).toBeNull()
    expect(oneOffAction(tx())).toBeNull()
  })
})

describe('totalsParts', () => {
  it('cuenta, total en RD$ y, si hay, los US$ sin tasa', () => {
    expect(
      totalsParts({
        items: [],
        count: 9,
        total_cents: 3_074_500,
        income_cents: 0,
        unconverted_usd_cents: 0,
      }),
    ).toEqual({ count: '9 transacciones', total: 'RD$ 30,745', income: null, unconverted: null })
    expect(
      totalsParts({
        items: [],
        count: 1,
        total_cents: 0,
        income_cents: 0,
        unconverted_usd_cents: 1_199,
      }),
    ).toEqual({
      count: '1 transacción',
      total: 'RD$ 0',
      income: null,
      unconverted: 'US$ 11.99 sin tasa',
    })
  })
})

describe('amountLines / originText', () => {
  it('pesos: un solo monto', () => {
    expect(amountLines(tx())).toEqual({ main: 'RD$ 1,980', original: null, credit: false })
    expect(originText(tx())).toBe('Cargado en pesos')
  })

  it('gasto compartido: tu parte y, debajo, el monto del estado', () => {
    const shared = tx({ amount_cents: 61_667, amount_dop_cents: 61_667, gross_cents: 185_000 })
    expect(amountLines(shared)).toEqual({ main: 'RD$ 617', original: 'de RD$ 1,850', credit: false })
  })

  it('dólares convertidos: RD$ arriba y el original en US$ debajo', () => {
    const usd = tx({ currency: 'USD', amount_cents: 1_199, amount_dop_cents: 76_017 })
    expect(amountLines(usd)).toEqual({ main: 'RD$ 760', original: 'US$ 11.99', credit: false })
    expect(originText(usd)).toBe('US$ 11.99 convertidos a la tasa del mes')
  })

  it('dólares sin tasa: el monto en US$ y el aviso', () => {
    const usd = tx({ currency: 'USD', amount_cents: 4_850, amount_dop_cents: null })
    expect(amountLines(usd)).toEqual({ main: 'US$ 48.50', original: 'sin tasa', credit: false })
    expect(originText(usd)).toBe('Sin tasa del mes: no cuenta en el total en RD$')
  })

  it('las devoluciones llevan "−" y se marcan como crédito', () => {
    const refund = tx({ amount_cents: -120_000, amount_dop_cents: -120_000 })
    expect(amountLines(refund)).toEqual({ main: '−RD$ 1,200', original: null, credit: true })
  })
})

describe('filtro por tipo', () => {
  it('lee `tipo` de la URL y lo pasa a la API como `kind`', () => {
    const filters = parseFilters(new URLSearchParams('mes=2026-01&tipo=ingresos'))
    expect(filters.kind).toBe('ingreso')
    expect(toParams(filters).toString()).toBe('mes=2026-01&tipo=ingresos')
    expect(apiPath('2026-01', filters)).toBe('/api/transactions?month=2026-01&kind=ingreso')
  })

  it('ignora un tipo desconocido', () => {
    expect(parseFilters(new URLSearchParams('tipo=otro')).kind).toBeNull()
  })

  it('cuenta como filtro y se quita con los demás', () => {
    const filters = parseFilters(new URLSearchParams('mes=2026-01&tipo=transferencias'))
    expect(hasNarrowing(filters)).toBe(true)
    expect(clearFilters(filters).kind).toBeNull()
  })
})

describe('totalsParts con ingresos', () => {
  it('agrega los ingresos de la lista cuando los hay', () => {
    expect(
      totalsParts({
        items: [],
        count: 3,
        total_cents: 500_000,
        income_cents: 9_700_000,
        unconverted_usd_cents: 0,
      }).income,
    ).toBe('ingresos RD$ 97,000')
  })
})

describe('kindBadge', () => {
  it('marca solo lo que no es gasto', () => {
    expect(kindBadge(tx())).toBeNull()
    expect(kindBadge(tx({ kind: 'ingreso' }))).toBe('Ingreso')
    expect(kindBadge(tx({ kind: 'transferencia' }))).toBe('Transferencia')
  })
})

describe('montos según el tipo', () => {
  it('un ingreso lleva "+" y tono de ingreso', () => {
    const deposit = tx({ kind: 'ingreso', amount_cents: -1_200_000, amount_dop_cents: -1_200_000 })
    expect(amountLines(deposit)).toEqual({ main: '+RD$ 12,000', original: null, credit: false })
    expect(amountTone(deposit)).toBe('income')
  })

  it('un ingreso en dólares lleva "+" también en el original', () => {
    const usd = tx({
      kind: 'ingreso',
      currency: 'USD',
      amount_cents: -10_000,
      amount_dop_cents: -634_000,
    })
    expect(amountLines(usd)).toEqual({ main: '+RD$ 6,340', original: '+US$ 100.00', credit: false })
  })

  it('un ingreso en dólares sin tasa: "+US$" y el aviso', () => {
    const usd = tx({ kind: 'ingreso', currency: 'USD', amount_cents: -10_000, amount_dop_cents: null })
    expect(amountLines(usd)).toEqual({ main: '+US$ 100.00', original: 'sin tasa', credit: false })
  })

  it('una devolución sigue en el tono de crédito y una transferencia queda neutra', () => {
    const refund = tx({ amount_cents: -120_000, amount_dop_cents: -120_000 })
    expect(amountTone(refund)).toBe('credit')
    expect(amountTone(tx())).toBe('plain')
    const payment = tx({ kind: 'transferencia', amount_cents: -600_000, amount_dop_cents: -600_000 })
    expect(amountLines(payment)).toEqual({ main: '−RD$ 6,000', original: null, credit: false })
    expect(amountTone(payment)).toBe('plain')
  })
})

describe('totalsParts sin gastos en la lista', () => {
  it('omite el total de gastos cuando solo hay ingresos', () => {
    const parts = totalsParts({
      items: [tx({ kind: 'ingreso', amount_cents: -100, amount_dop_cents: -100 })],
      count: 1,
      total_cents: 0,
      income_cents: 100,
      unconverted_usd_cents: 0,
    })
    expect(parts.total).toBeNull()
    expect(parts.income).toBe('ingresos RD$ 1')
  })

  it('con gastos en la lista lo muestra aunque sea cero', () => {
    const parts = totalsParts({
      items: [tx({ amount_cents: 0, amount_dop_cents: 0 })],
      count: 1,
      total_cents: 0,
      income_cents: 0,
      unconverted_usd_cents: 0,
    })
    expect(parts.total).toBe('RD$ 0')
  })
})

describe('agrupar y ordenar en la URL', () => {
  it('lee `agrupar` y `orden`; ausente o desconocido es por día y por fecha', () => {
    const view = parseFilters(new URLSearchParams('agrupar=categoria&orden=monto'))
    expect([view.group, view.sort]).toEqual(['category', 'amount'])
    expect(parseFilters(new URLSearchParams('agrupar=comercio')).group).toBe('merchant')
    const unknown = parseFilters(new URLSearchParams('agrupar=otro&orden=raro'))
    expect([unknown.group, unknown.sort]).toEqual(['day', 'date'])
  })

  it('escribe solo lo que no es el valor por defecto', () => {
    const base = parseFilters(new URLSearchParams('mes=2026-01'))
    expect(toParams(base).toString()).toBe('mes=2026-01')
    expect(toParams({ ...base, group: 'category', sort: 'amount' }).toString()).toBe(
      'mes=2026-01&agrupar=categoria&orden=monto',
    )
    expect(toParams({ ...base, group: 'merchant' }).toString()).toBe('mes=2026-01&agrupar=comercio')
  })

  it('no recorta la lista: no cuenta como filtro ni va a la API', () => {
    const filters = parseFilters(new URLSearchParams('mes=2026-01&agrupar=comercio&orden=monto'))
    expect(hasNarrowing(filters)).toBe(false)
    expect(apiPath('2026-01', filters)).toBe('/api/transactions?month=2026-01')
  })
})

describe('sortItems', () => {
  const small = tx({ fingerprint: 's', amount_cents: 50_000, amount_dop_cents: 50_000 })
  const big = tx({ fingerprint: 'b', amount_cents: 900_000, amount_dop_cents: 900_000 })
  const refund = tx({ fingerprint: 'r', amount_cents: -300_000, amount_dop_cents: -300_000 })
  const noRate = tx({ fingerprint: 'n', currency: 'USD', amount_cents: 99_999, amount_dop_cents: null })

  it('por fecha deja el orden de la API', () => {
    const items = [small, big, refund]
    expect(sortItems(items, 'date')).toBe(items)
  })

  it('por monto: mayor primero por valor absoluto en RD$; sin tasa al final', () => {
    const items = [noRate, small, refund, big]
    expect(sortItems(items, 'amount').map((t) => t.fingerprint)).toEqual(['b', 'r', 's', 'n'])
    expect(items.map((t) => t.fingerprint)).toEqual(['n', 's', 'r', 'b'])
  })

  it('a igual monto conserva el orden de la API', () => {
    const a = tx({ fingerprint: 'a' })
    const b = tx({ fingerprint: 'b' })
    expect(sortItems([a, b], 'amount')).toEqual([a, b])
  })
})

describe('dayGroups', () => {
  it('por fecha es lo mismo que groupByDay', () => {
    const items = [tx({ fingerprint: 'a', day: '2026-09-29' }), tx({ fingerprint: 'b' })]
    expect(dayGroups(items, 'date')).toEqual(groupByDay(items))
  })

  it('por monto ordena dentro de cada día y no mezcla los días', () => {
    const items = [
      tx({ fingerprint: 'a', day: '2026-09-29', amount_dop_cents: 10_000 }),
      tx({ fingerprint: 'b', day: '2026-09-29', amount_dop_cents: 70_000 }),
      tx({ fingerprint: 'c', day: '2026-09-27', amount_dop_cents: 5_000 }),
    ]
    const groups = dayGroups(items, 'amount')
    expect(groups.map((g) => g.day)).toEqual(['2026-09-29', '2026-09-27'])
    expect(groups[0].items.map((t) => t.fingerprint)).toEqual(['b', 'a'])
  })
})

describe('totalsOf', () => {
  it('suma como el encabezado: gastos convertidos, ingresos en positivo y US$ sin tasa', () => {
    const items = [
      tx({ amount_dop_cents: 100_000 }),
      tx({ amount_cents: -20_000, amount_dop_cents: -20_000 }),
      tx({ kind: 'ingreso', amount_cents: -500_000, amount_dop_cents: -500_000 }),
      tx({ kind: 'transferencia', amount_dop_cents: 900_000 }),
      tx({ currency: 'USD', amount_cents: 1_199, amount_dop_cents: null }),
    ]
    expect(totalsOf(items)).toEqual({
      items,
      count: 5,
      total_cents: 80_000,
      income_cents: 500_000,
      unconverted_usd_cents: 1_199,
    })
  })
})

describe('fieldGroups', () => {
  const lunch = tx({ fingerprint: 'l', merchant: 'Café', category: 'Restaurantes', amount_dop_cents: 30_000 })
  const dinner = tx({ fingerprint: 'd', merchant: 'Bistró', category: 'Restaurantes', amount_dop_cents: 60_000 })
  const fuel = tx({ fingerprint: 'f', merchant: 'Gasolinera', category: 'Vehículo', amount_dop_cents: 200_000 })
  const salary = tx({
    fingerprint: 's',
    merchant: 'Nómina',
    category: 'Salario',
    kind: 'ingreso',
    amount_cents: -8_000_000,
    amount_dop_cents: -8_000_000,
  })
  const card = tx({ fingerprint: 'c', merchant: 'Pago', category: 'Pago de tarjeta', kind: 'transferencia', amount_dop_cents: 999_000 })

  it('por categoría: nombre, cantidad y total; de mayor a menor gasto', () => {
    const groups = fieldGroups([lunch, fuel, dinner], 'category', 'date')
    expect(groups.map((g) => [g.key, g.items.map((t) => t.fingerprint)])).toEqual([
      ['Vehículo', ['f']],
      ['Restaurantes', ['l', 'd']],
    ])
    expect(groupLine(groups[1])).toBe('2 transacciones · RD$ 900')
    expect(groupLine(groups[0])).toBe('1 transacción · RD$ 2,000')
  })

  it('por comercio agrupa por el nombre del comercio', () => {
    const again = tx({ fingerprint: 'l2', merchant: 'Café', amount_dop_cents: 10_000 })
    const groups = fieldGroups([lunch, dinner, again], 'merchant', 'date')
    expect(groups.map((g) => g.key)).toEqual(['Bistró', 'Café'])
    expect(groups[1].items.map((t) => t.fingerprint)).toEqual(['l', 'l2'])
  })

  it('los grupos sin gastos van después, por ingresos y luego por monto movido', () => {
    const groups = fieldGroups([card, salary, lunch], 'category', 'date')
    expect(groups.map((g) => g.key)).toEqual(['Restaurantes', 'Salario', 'Pago de tarjeta'])
    expect(groupLine(groups[1])).toBe('1 transacción · ingresos RD$ 80,000')
    expect(groupLine(groups[2])).toBe('1 transacción')
  })

  it('a igual gasto en RD$, va primero el grupo con US$ sin tasa', () => {
    const usd = tx({ merchant: 'App', category: 'Apps', currency: 'USD', amount_cents: 1_199, amount_dop_cents: null })
    const groups = fieldGroups([salary, usd], 'category', 'date')
    expect(groups.map((g) => g.key)).toEqual(['Apps', 'Salario'])
  })

  it('ordena por monto dentro de cada grupo', () => {
    const groups = fieldGroups([lunch, dinner], 'category', 'amount')
    expect(groups[0].items.map((t) => t.fingerprint)).toEqual(['d', 'l'])
  })

  it('un grupo con US$ sin tasa lo dice como el encabezado', () => {
    const usd = tx({ merchant: 'App', currency: 'USD', amount_cents: 1_199, amount_dop_cents: null })
    expect(groupLine(fieldGroups([usd], 'merchant', 'date')[0])).toBe(
      '1 transacción · RD$ 0 · US$ 11.99 sin tasa',
    )
  })
})

describe('outOfView', () => {
  it('una fila entera en la ventana no se mueve; cortada o fuera, sí', () => {
    expect(outOfView({ top: 200, bottom: 244 }, 800)).toBe(false)
    expect(outOfView({ top: 780, bottom: 824 }, 800)).toBe(true)
    expect(outOfView({ top: 1500, bottom: 1544 }, 800)).toBe(true)
    expect(outOfView({ top: 20, bottom: 64 }, 800)).toBe(true) // debajo del encabezado fijo
  })
})
