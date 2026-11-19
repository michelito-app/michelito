import { describe, expect, it } from 'vitest'
import type { AccountTotal, CategoryLine, Change, MonthTotal, Rate } from './api'
import {
  accountNote,
  barWidth,
  byMovement,
  categoryDiff,
  changeDetail,
  changeTitle,
  coverageText,
  oneOffsText,
  partialNote,
  parseRate,
  rateNote,
  rateText,
  netDetail,
  netText,
  netTone,
  NO_FLOW_NOTE,
  ownMovesNote,
  spendingHref,
  thirdPartyHref,
  thirdPartyNote,
  incomeThroughNote,
  savingsNote,
  savingsText,
  splitTop,
  trendIncomeNote,
  trendMonthAt,
  trendSummary,
  versusHabitual,
} from './summary'

function line(overrides: Partial<CategoryLine>): CategoryLine {
  return {
    category: 'Supermercado',
    amount_cents: 3420000,
    habitual_cents: 3290000,
    diff_cents: 130000,
    same: false,
    share: 0.23,
    one_offs_cents: 0,
    purchases: 10,
    habitual_purchases: 10,
    ...overrides,
  }
}

function change(overrides: Partial<Change>): Change {
  return {
    category: 'Delivery',
    diff_cents: 440000,
    one_offs_cents: 0,
    purchases: 14,
    habitual_purchases: 8,
    ...overrides,
  }
}

/** Un mes completo de la tendencia, sin marcas de mes atípico. */
function point(month: string, label: string, totalCents: number, incomeCents: number): MonthTotal {
  return {
    month,
    label,
    total_cents: totalCents,
    income_cents: incomeCents,
    partial: false,
    spent_flag: null,
    spent_habitual_cents: null,
    income_flag: null,
    income_habitual_cents: null,
  }
}

const RATE: Rate ={ value: '63.4000', month_used: '2026-09', source: 'bcrd' }

describe('categoryDiff', () => {
  it('sube en naranja y baja en azul', () => {
    expect(categoryDiff(line({}))).toEqual({ tone: 'up', text: '+RD$ 1,300' })
    expect(categoryDiff(line({ diff_cents: -255000 }))).toEqual({ tone: 'down', text: '−RD$ 2,550' })
  })
  it('"igual" cuando la API la marca como igual', () => {
    expect(categoryDiff(line({ diff_cents: 20000, same: true }))).toEqual({
      tone: 'same',
      text: 'igual',
    })
  })
  it('"—" en un mes incompleto (sin habitual)', () => {
    expect(categoryDiff(line({ diff_cents: null, habitual_cents: null }))).toEqual({
      tone: 'none',
      text: '—',
    })
  })
  it('"nuevo" cuando antes no había gasto en la categoría', () => {
    const fresh = line({ amount_cents: 7547600, habitual_cents: 0, diff_cents: 7547600 })
    expect(categoryDiff(fresh)).toEqual({ tone: 'up', text: 'nuevo' })
    expect(categoryDiff({ ...fresh, one_offs_cents: 7547600 }).text).toBe('nuevo · único')
  })
  it('marca las subidas que traen un gasto único', () => {
    expect(categoryDiff(line({ diff_cents: 1150000, one_offs_cents: 1250000 })).text).toBe(
      '+RD$ 11,500 · único',
    )
  })
})

describe('barWidth', () => {
  it('escala contra la categoría mayor', () => {
    expect(barWidth(500, 1000)).toBe(50)
    expect(barWidth(1000, 1000)).toBe(100)
  })
  it('se limita a 0..100 aunque haya devoluciones', () => {
    expect(barWidth(-300, 1000)).toBe(0)
    expect(barWidth(1500, 1000)).toBe(100)
    expect(barWidth(500, 0)).toBe(0)
  })
})

describe('versusHabitual', () => {
  it('dice cuánto más o menos que lo habitual', () => {
    expect(versusHabitual(14832000, 13490000)).toEqual({
      tone: 'up',
      text: 'RD$ 13,420 más que lo habitual',
    })
    expect(versusHabitual(12000000, 13490000)).toEqual({
      tone: 'down',
      text: 'RD$ 14,900 menos que lo habitual',
    })
  })
  it('"casi igual" dentro de max(RD$ 500, 5 %)', () => {
    expect(versusHabitual(13582000, 13490000)).toEqual({
      tone: 'same',
      text: 'Casi igual a lo habitual (RD$ 134,900)',
    })
    expect(versusHabitual(140000, 100000)).toEqual({
      tone: 'same',
      text: 'Casi igual a lo habitual (RD$ 1,000)',
    })
  })
})

describe('changeTitle / changeDetail', () => {
  it('titula con la categoría y la diferencia en RD$', () => {
    expect(changeTitle(change({}))).toBe('Delivery +RD$ 4,400')
    expect(changeTitle(change({ category: 'Hogar', diff_cents: -255000 }))).toBe(
      'Hogar −RD$ 2,550',
    )
  })
  it('explica primero el gasto único', () => {
    expect(changeDetail(change({ one_offs_cents: 1250000 }))).toBe(
      'Incluye RD$ 12,500 marcado como gasto único',
    )
  })
  it('compara el número de compras', () => {
    expect(changeDetail(change({}))).toBe('14 compras; lo habitual son 8')
    expect(changeDetail(change({ purchases: 1, habitual_purchases: 3 }))).toBe(
      '1 compra; lo habitual son 3',
    )
    expect(changeDetail(change({ purchases: 0, diff_cents: -1000 }))).toBe(
      'Sin compras este mes',
    )
  })
  it('con las mismas compras habla del monto', () => {
    expect(changeDetail(change({ purchases: 8 }))).toBe('Las mismas compras, por más dinero')
    expect(changeDetail(change({ purchases: 8, diff_cents: -1000 }))).toBe(
      'Las mismas compras, por menos dinero',
    )
  })
})

describe('coverageText', () => {
  it('dice si la cuenta cubre el mes o hasta cuándo llega', () => {
    expect(coverageText({ key: 'a', label: 'A', through: '2026-10-31', complete: true })).toBe(
      'completo',
    )
    expect(coverageText({ key: 'a', label: 'A', through: '2026-10-13', complete: false })).toBe(
      'hasta 13 oct',
    )
    expect(coverageText({ key: 'a', label: 'A', through: null, complete: false })).toBe(
      'sin datos',
    )
  })
})

describe('rateText / rateNote', () => {
  it('muestra la tasa con 2 a 4 decimales', () => {
    expect(rateText('63.4000')).toBe('63.40')
    expect(rateText('63.4512')).toBe('63.4512')
  })
  it('avisa cuando la tasa es de otro mes', () => {
    expect(rateNote(RATE, '2026-09')).toBeNull()
    expect(rateNote({ ...RATE, month_used: '2026-08' }, '2026-09')).toBe('tasa de agosto')
  })
})

describe('parseRate', () => {
  it('acepta números positivos con hasta 4 decimales', () => {
    expect(parseRate(' 63.4 ')).toBe('63.4')
    expect(parseRate('63,45')).toBe('63.45')
    expect(parseRate('64')).toBe('64')
  })
  it('rechaza vacío, cero, negativos y texto', () => {
    expect(parseRate('')).toBeNull()
    expect(parseRate('0')).toBeNull()
    expect(parseRate('0.0000')).toBeNull()
    expect(parseRate('-5')).toBeNull()
    expect(parseRate('abc')).toBeNull()
    expect(parseRate('63.12345')).toBeNull()
  })
})

describe('accountNote', () => {
  const account: AccountTotal = { key: 'k', label: 'Visa', total_cents: 1978000, usd_cents: 0 }
  it('solo pesos', () => {
    expect(accountNote(account, RATE)).toBe('RD$')
  })
  it('con dólares dice a qué tasa, o que no la hay', () => {
    expect(accountNote({ ...account, usd_cents: 31200 }, RATE)).toBe('US$ 312.00 a 63.40')
    expect(accountNote({ ...account, usd_cents: 31200 }, null)).toBe(
      'US$ 312.00 sin tasa: no están en el total',
    )
  })
})

describe('trendSummary', () => {
  const trend: MonthTotal[] = [
    point('2026-07', 'jul', 9_000_000, 0),
    point('2026-08', 'ago', 8_700_000, 0),
    point('2026-09', 'sep', 9_700_000, 15_000_000),
    point('2026-10', 'oct', 9_900_000, 0),
  ]
  it('resume el rango y la posición del mes elegido', () => {
    expect(trendSummary(trend, '2026-09')).toBe(
      'Gasto mensual de julio 2026 a octubre 2026; septiembre: RD$ 97,000, el segundo más alto',
    )
    expect(trendSummary(trend, '2026-10')).toMatch(/octubre: RD\$ 99,000, el más alto$/)
    expect(trendSummary(trend, '2026-08')).toMatch(/agosto: RD\$ 87,000, el más bajo$/)
    expect(trendSummary(trend, '2026-07')).toMatch(/julio: RD\$ 90,000, el tercero más alto$/)
  })
  it('con un solo mes no compara', () => {
    expect(trendSummary(trend.slice(0, 1), '2026-07')).toBe(
      'Gasto mensual de julio 2026: RD$ 90,000',
    )
  })
})

describe('oneOffsText', () => {
  const lines = [
    line({ category: 'Salud', one_offs_cents: 1250000 }),
    line({ category: 'Hogar', one_offs_cents: 0 }),
    line({ category: 'Viajes', one_offs_cents: 300000 }),
  ]
  it('nombra las categorías con gastos únicos', () => {
    expect(oneOffsText(lines.slice(0, 2))).toBe('En Salud')
    expect(oneOffsText(lines)).toBe('En Salud y Viajes')
    expect(oneOffsText([...lines, line({ category: 'Ropa', one_offs_cents: 1 })])).toBe(
      'En 3 categorías',
    )
  })
  it('sin gastos únicos no hay texto', () => {
    expect(oneOffsText([lines[1]])).toBeNull()
  })
})

describe('partialNote', () => {
  it('dice hasta dónde llega cada cuenta que no cubre el mes', () => {
    expect(
      partialNote('Octubre 2026', [
        { key: 'a', label: 'Visa ···1234', through: '2026-10-31', complete: true },
        { key: 'b', label: 'MC ···5151', through: '2026-10-13', complete: false },
        { key: 'c', label: 'Ahorro ···1', through: null, complete: false },
      ]),
    ).toBe(
      'Octubre 2026 está incompleto: MC ···5151 tiene datos hasta el 13 de octubre y ' +
        'Ahorro ···1 no tiene datos. Se compara cuando todas las cuentas cierran el mes.',
    )
  })
})

describe('trendMonthAt', () => {
  const trend: MonthTotal[] = [
    point('2026-08', 'ago', 8_700_000, 0),
    point('2026-09', 'sep', 9_700_000, 0),
  ]
  it('devuelve el mes de la barra pulsada', () => {
    expect(trendMonthAt(trend, 1)).toBe('2026-09')
    expect(trendMonthAt(trend, '0')).toBe('2026-08')
  })
  it('ignora clics fuera de las barras', () => {
    expect(trendMonthAt(trend, undefined)).toBeNull()
    expect(trendMonthAt(trend, 5)).toBeNull()
    expect(trendMonthAt(trend, 'x')).toBeNull()
  })
})

describe('savingsText', () => {
  it('redondea a un porcentaje entero', () => {
    expect(savingsText(0.8375)).toBe('84 %')
    expect(savingsText(0)).toBe('0 %')
  })
  it('un mes en rojo da un porcentaje negativo', () => {
    expect(savingsText(-0.25)).toBe('−25 %')
  })
  it('sin ingresos: "—"', () => {
    expect(savingsText(null)).toBe('—')
  })
})

describe('incomeThroughNote', () => {
  it('dice hasta qué día se conocen los ingresos', () => {
    expect(incomeThroughNote('2026-01-15')).toBe('Hasta el 15 ene')
  })
  it('sin corte, nada', () => {
    expect(incomeThroughNote(null)).toBeNull()
  })
})

describe('savingsNote', () => {
  it('con ingresos completos explica el porcentaje', () => {
    expect(savingsNote(0.5, null)).toBe('De lo que entró, lo que quedó')
  })
  it('sin ingresos no se calcula', () => {
    expect(savingsNote(null, null)).toBe('Sin ingresos: no se calcula')
  })
  it('con ingresos incompletos tampoco, y dice hasta cuándo', () => {
    expect(savingsNote(null, '2026-01-15')).toBe('Ingresos hasta el 15 ene: no se calcula')
  })
})

describe('netTone / netDetail', () => {
  it('lo que quedó es bueno si no es negativo', () => {
    expect(netTone(0)).toBe('good')
    expect(netTone(100)).toBe('good')
    expect(netTone(-1)).toBe('up')
  })
  it('explica el número', () => {
    expect(netDetail(500_000)).toBe('Ingresos menos gastos')
    expect(netDetail(-500_000)).toBe('Gastaste RD$ 5,000 más de lo que entró')
  })
  it('nombra las transferencias a terceros cuando las hubo', () => {
    expect(netDetail(500_000, 120_000)).toBe('Ingresos menos gastos y transferencias a terceros')
    expect(netDetail(500_000, 0)).toBe('Ingresos menos gastos')
    expect(netDetail(-500_000, 120_000)).toBe('Salió RD$ 5,000 más de lo que entró')
  })
})

describe('spendingHref', () => {
  it('lleva a los gastos del mes en Transacciones, agrupados por categoría', () => {
    const href = spendingHref('2026-09')
    expect(href.startsWith('/transacciones?')).toBe(true)
    const params = new URLSearchParams(href.split('?')[1])
    expect(params.get('mes')).toBe('2026-09')
    expect(params.get('tipo')).toBe('gastos')
    expect(params.get('agrupar')).toBe('categoria')
    expect(params.has('cuentas')).toBe(false)
  })
  it('conserva las cuentas elegidas', () => {
    const params = new URLSearchParams(spendingHref('2026-09', ['bhd:1']).split('?')[1])
    expect(params.get('cuentas')).toBe('bhd:1')
  })
})

describe('thirdPartyHref / thirdPartyNote', () => {
  it('lleva a Transacciones filtradas por la categoría y el mes', () => {
    const href = thirdPartyHref('2026-09')
    expect(href.startsWith('/transacciones?')).toBe(true)
    const params = new URLSearchParams(href.split('?')[1])
    expect(params.get('mes')).toBe('2026-09')
    expect(params.get('categoria')).toBe('Transferencias a terceros')
  })
  it('explica que no es gasto, o que no hubo', () => {
    expect(thirdPartyNote(120_000)).toBe('No es gasto; sí resta de lo que te quedó')
    expect(thirdPartyNote(0)).toBe('Ninguna este mes')
  })
})

describe('trendIncomeNote', () => {
  const trend: MonthTotal[] = [
    point('2026-08', 'ago', 8_700_000, 0),
    point('2026-09', 'sep', 9_700_000, 15_000_000),
  ]
  it('dice cuánto entró en el mes elegido', () => {
    expect(trendIncomeNote(trend, '2026-09')).toBe('Ingresos de septiembre: RD$ 150,000')
    expect(trendIncomeNote(trend, '2026-08')).toBe('Sin ingresos en agosto')
  })
  it('sin el mes no dice nada', () => {
    expect(trendIncomeNote(trend, '2026-01')).toBeNull()
  })
})

describe('cuentas elegidas', () => {
  it('el enlace a terceros lleva la selección', () => {
    expect(thirdPartyHref('2026-01', ['a', 'b'])).toBe(
      '/transacciones?mes=2026-01&categoria=Transferencias+a+terceros&cuentas=a%2Cb',
    )
  })

  it('sin flujo, "Te quedó" es una raya y la nota pide una cuenta con ingresos', () => {
    expect(netText(null)).toBe('—')
    expect(netText(150_000)).toBe('RD$ 1,500')
    expect(NO_FLOW_NOTE).toBe('Elige una cuenta con ingresos para ver el flujo')
  })

  it('lo que salió hacia otras cuentas tuyas; nada si los dos son cero', () => {
    expect(ownMovesNote(800_000, 40_000)).toBe(
      'Pagos a tus tarjetas RD$ 8,000 · Movido a tus otras cuentas RD$ 400',
    )
    expect(ownMovesNote(800_000, 0)).toBe('Pagos a tus tarjetas RD$ 8,000')
    expect(ownMovesNote(0, 40_000)).toBe('Movido a tus otras cuentas RD$ 400')
    expect(ownMovesNote(0, 0)).toBeNull()
  })
})

describe('splitTop', () => {
  const items = ['a', 'b', 'c', 'd', 'e']
  it('parte en las primeras N y el resto', () => {
    expect(splitTop(items, 3)).toEqual({ shown: ['a', 'b', 'c'], rest: ['d', 'e'] })
  })
  it('con pocas filas no hay resto', () => {
    expect(splitTop(items, 5)).toEqual({ shown: items, rest: [] })
    expect(splitTop([], 8)).toEqual({ shown: [], rest: [] })
  })
  it('abierto, todo va a la vista', () => {
    expect(splitTop(items, 3, true)).toEqual({ shown: items, rest: [] })
  })
})

describe('byMovement', () => {
  it('ordena las cuentas de mayor a menor gasto sin tocar la lista', () => {
    const list: AccountTotal[] = [
      { key: 'a', label: 'A', total_cents: 100, usd_cents: 0 },
      { key: 'b', label: 'B', total_cents: 900, usd_cents: 0 },
    ]
    expect(byMovement(list).map((a) => a.key)).toEqual(['b', 'a'])
    expect(list[0].key).toBe('a')
  })
})
