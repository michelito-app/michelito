import { describe, expect, it } from 'vitest'
import type { GroupTotal, Recurring, RecurringItem } from './api'
import {
  alertTone,
  badgeTone,
  badgesOf,
  cardNote,
  cadenceText,
  chargeText,
  costLines,
  extrasText,
  GROUP_OPTIONS,
  groupBody,
  installmentsBody,
  joinTargets,
  lastChargeText,
  membersText,
  nextChargeDay,
  parseInstallments,
  sections,
  separableMembers,
  sinceText,
  statusBody,
  totalLine,
  txRecurringBody,
  typicalDay,
  upcomingCharges,
} from './recurring'

function item(overrides: Partial<RecurringItem> = {}): RecurringItem {
  return {
    merchant: 'STREAMING FICTICIO',
    currency: 'USD',
    category: 'Suscripciones digitales',
    group: 'Suscripciones',
    cadence: 'mensual',
    status: 'activo',
    typical_cents: 1199,
    variable: false,
    monthly_cents: 76376,
    yearly_cents: 916516,
    first_day: '2025-12-05',
    last_day: '2026-02-05',
    charges: 3,
    price_change: null,
    installments_left: null,
    mark: null,
    charged_after_cancel: false,
    name: overrides.merchant ?? 'STREAMING FICTICIO',
    members: [overrides.merchant ?? 'STREAMING FICTICIO'],
    provider: false,
    extras_year_cents: 0,
    group_key: 'suscripciones',
    ...overrides,
  }
}

function total(group: string, monthly: number): GroupTotal {
  return {
    group,
    monthly_cents: monthly,
    yearly_cents: monthly * 12,
    count: 1,
  }
}

function overview(items: RecurringItem[], groups: GroupTotal[]): Recurring {
  return {
    as_of: '2026-02-08',
    first_month: '2025-12',
    monthly_cents: 0,
    groups,
    items,
    dismissed: [],
    alerts: [],
    providers: [],
  }
}

describe('badgesOf', () => {
  it('no pone insignias a un recurrente activo sin cambios', () => {
    expect(badgesOf(item(), '2026-02')).toEqual([])
  })

  it('marca "Subió" solo cuando el precio sube', () => {
    const up = { before_cents: 999, after_cents: 1199, day: '2026-02-05' }
    const down = { before_cents: 1199, after_cents: 999, day: '2026-02-05' }
    expect(badgesOf(item({ price_change: up }), '2026-02')).toEqual(['Subió'])
    expect(badgesOf(item({ price_change: down }), '2026-02')).toEqual([])
  })

  it('marca "Nuevo" cuando el primer cobro cae en el mes de referencia', () => {
    expect(badgesOf(item({ first_day: '2026-02-03' }), '2026-02')).toEqual(['Nuevo'])
    expect(badgesOf(item({ first_day: '2026-02-03' }), null)).toEqual([])
  })

  it('no marca "Nuevo" en el primer mes con datos', () => {
    const first = item({ first_day: '2025-12-03' })
    expect(badgesOf(first, '2025-12', '2025-12')).toEqual([])
    expect(badgesOf(first, '2025-12', '2025-11')).toEqual(['Nuevo'])
  })

  it('"Subió" solo en el mes del cambio y "Nuevo"/"Subió" solo en activos', () => {
    const up = { before_cents: 999, after_cents: 1199, day: '2026-01-05' }
    expect(badgesOf(item({ price_change: up }), '2026-02')).toEqual([])
    const cancelled = item({
      price_change: { ...up, day: '2026-02-05' },
      status: 'cancelado',
    })
    expect(badgesOf(cancelled, '2026-02')).toEqual(['Cancelado'])
    expect(badgesOf(item({ first_day: '2026-02-03', status: 'inactivo' }), '2026-02')).toEqual([
      'Inactivo',
    ])
  })

  it('avisa el cobro tras cancelar antes que el estado', () => {
    const cancelled = item({
      status: 'cancelado',
      mark: 'cancelled',
      charged_after_cancel: true,
    })
    expect(badgesOf(cancelled, null)).toEqual(['Te volvieron a cobrar', 'Cancelado'])
  })

  it('incluye monto variable, cuotas y estados', () => {
    expect(badgesOf(item({ variable: true }), null)).toEqual(['Variable'])
    expect(badgesOf(item({ installments_left: 4 }), null)).toEqual(['4 cuotas restantes'])
    expect(badgesOf(item({ installments_left: 1 }), null)).toEqual(['1 cuota restante'])
    expect(badgesOf(item({ installments_left: 0, status: 'terminado' }), null)).toEqual([
      'Terminado',
    ])
    expect(badgesOf(item({ status: 'inactivo' }), null)).toEqual(['Inactivo'])
  })
})

describe('badgeTone', () => {
  it('usa el tono de alerta para subidas y cobros tras cancelar', () => {
    expect(badgeTone('Subió')).toBe('up')
    expect(badgeTone('Te volvieron a cobrar')).toBe('up')
  })

  it('distingue cuotas, estados apagados y lo neutral', () => {
    expect(badgeTone('3 cuotas restantes')).toBe('positive')
    expect(badgeTone('1 cuota restante')).toBe('positive')
    expect(badgeTone('Inactivo')).toBe('muted')
    expect(badgeTone('Cancelado')).toBe('muted')
    expect(badgeTone('Terminado')).toBe('muted')
    expect(badgeTone('Nuevo')).toBe('neutral')
    expect(badgeTone('Variable')).toBe('neutral')
  })
})

describe('alertTone', () => {
  it('sube el tono de "subió" y del cobro tras cancelar; "nuevo" es neutral', () => {
    expect(alertTone('subio')).toBe('up')
    expect(alertTone('cobro_tras_cancelar')).toBe('up')
    expect(alertTone('nuevo')).toBe('neutral')
  })
})

describe('textos de la fila', () => {
  it('cadenceText dice mensual o anual', () => {
    expect(cadenceText(item())).toBe('mensual')
    expect(cadenceText(item({ cadence: 'anual' }))).toBe('anual')
  })

  it('sinceText usa mes abreviado y año de dos cifras', () => {
    expect(sinceText(item())).toBe('desde dic 25')
  })

  it('lastChargeText usa día y mes abreviado', () => {
    expect(lastChargeText(item())).toBe('último cobro 5 feb')
  })
})

describe('costLines', () => {
  it('un US$ mensual muestra RD$ y el original', () => {
    expect(costLines(item())).toEqual({
      main: 'RD$ 764',
      detail: 'US$ 11.99 al mes',
    })
  })

  it('un RD$ mensual solo dice "al mes"', () => {
    const gym = item({
      currency: 'DOP',
      typical_cents: 250000,
      monthly_cents: 250000,
    })
    expect(costLines(gym)).toEqual({ main: 'RD$ 2,500', detail: 'al mes' })
  })

  it('un anual muestra el cobro original al año', () => {
    const yearly = item({
      currency: 'DOP',
      cadence: 'anual',
      typical_cents: 360000,
      monthly_cents: 30000,
    })
    expect(costLines(yearly)).toEqual({
      main: 'RD$ 300',
      detail: 'RD$ 3,600 al año',
    })
  })

  it('sin tasa, un US$ se muestra en su moneda', () => {
    expect(costLines(item({ monthly_cents: null, yearly_cents: null }))).toEqual({
      main: 'US$ 11.99',
      detail: 'al mes · sin tasa',
    })
  })

  it('un monto variable dice que es promedio', () => {
    const power = item({
      currency: 'DOP',
      variable: true,
      monthly_cents: 310000,
    })
    expect(costLines(power)).toEqual({
      main: 'RD$ 3,100',
      detail: 'promedio al mes',
    })
  })
})

describe('totalLine', () => {
  it('une el total mensual y el anual', () => {
    expect(totalLine(326376, 3916516)).toBe('RD$ 3,264 al mes · RD$ 39,165 al año')
  })
})

describe('sections', () => {
  it('agrupa en el orden de la API y deja los apagados al final del grupo', () => {
    const off = item({ merchant: 'VIEJO', status: 'inactivo' })
    const on = item({ merchant: 'NUEVO' })
    const gym = item({ merchant: 'GIMNASIO', group: 'Otros recurrentes' })
    const result = sections(
      overview([off, on, gym], [total('Suscripciones', 76376), total('Otros recurrentes', 2500)]),
    )
    expect(result.map((s) => s.group)).toEqual(['Suscripciones', 'Otros recurrentes'])
    expect(result[0].items.map((i) => i.merchant)).toEqual(['NUEVO', 'VIEJO'])
    expect(result[0].total?.monthly_cents).toBe(76376)
  })

  it('un grupo sin activos no tiene total', () => {
    const result = sections(overview([item({ status: 'cancelado' })], []))
    expect(result[0].total).toBeNull()
  })
})

describe('cuerpos de la marca', () => {
  it('statusBody no manda las cuotas', () => {
    expect(statusBody(item(), 'dismissed')).toEqual({
      merchant: 'STREAMING FICTICIO',
      currency: 'USD',
      status: 'dismissed',
    })
  })

  it('installmentsBody conserva la marca actual y manda las cuotas explícitas', () => {
    expect(installmentsBody(item({ mark: 'confirmed' }), 5)).toEqual({
      merchant: 'STREAMING FICTICIO',
      currency: 'USD',
      status: 'confirmed',
      installments_left: 5,
    })
    expect(installmentsBody(item(), null)).toEqual({
      merchant: 'STREAMING FICTICIO',
      currency: 'USD',
      status: null,
      installments_left: null,
    })
  })
})

describe('parseInstallments', () => {
  it('acepta enteros de 0 a 600', () => {
    expect(parseInstallments('0')).toBe(0)
    expect(parseInstallments(' 12 ')).toBe(12)
    expect(parseInstallments('600')).toBe(600)
  })

  it('rechaza lo vacío, decimales, negativos y más de 600', () => {
    for (const text of ['', '1.5', '-1', '601', 'doce']) expect(parseInstallments(text)).toBeNull()
  })
})

describe('cardNote', () => {
  it('sin recurrentes lo dice en vez de "RD$ 0 al mes"', () => {
    expect(cardNote(overview([], []))).toBe('Sin cargos recurrentes detectados')
  })

  it('con recurrentes y sin avisos dice que no hubo cambios', () => {
    expect(cardNote(overview([item()], []))).toBe('Sin cambios este mes')
  })

  it('con avisos no hay nota', () => {
    const data = {
      ...overview([item()], []),
      alerts: [
        {
          kind: 'subio' as const,
          merchant: 'X',
          currency: 'USD',
          detail: 'Subió',
          name: 'X',
        },
      ],
    }
    expect(cardNote(data)).toBeNull()
  })
})

describe('próximos cobros', () => {
  const TODAY = '2026-02-01'

  it('el siguiente es un mes (o un año) después, sin pasarse del fin de mes', () => {
    const at = (first_day: string, last_day: string, cadence: 'mensual' | 'anual' = 'mensual') =>
      nextChargeDay({ first_day, last_day, cadence }, '2000-01-01')
    expect(at('2025-12-05', '2026-02-05')).toBe('2026-03-05')
    expect(at('2025-12-31', '2026-01-31')).toBe('2026-02-28')
    expect(at('2025-11-15', '2025-12-15')).toBe('2026-01-15')
    expect(at('2023-02-28', '2024-02-29', 'anual')).toBe('2025-02-28')
  })

  it('usa el día típico, no el recortado por un mes corto', () => {
    expect(typicalDay({ first_day: '2025-12-31', last_day: '2026-02-28' })).toBe(31)
    expect(typicalDay({ first_day: '2025-12-05', last_day: '2026-02-08' })).toBe(8)
    expect(typicalDay({ first_day: '2025-12-15', last_day: '2026-02-28' })).toBe(28)
    const late = { first_day: '2025-12-31', last_day: '2026-02-28', cadence: 'mensual' as const }
    expect(nextChargeDay(late, '2026-03-01')).toBe('2026-03-31')
  })

  it('avanza hasta no quedar antes de hoy', () => {
    const old = { first_day: '2025-06-10', last_day: '2025-09-10', cadence: 'mensual' as const }
    expect(nextChargeDay(old, '2026-02-11')).toBe('2026-03-10')
    expect(nextChargeDay(old, '2026-02-10')).toBe('2026-02-10')
    const yearly = { first_day: '2023-05-20', last_day: '2024-05-20', cadence: 'anual' as const }
    expect(nextChargeDay(yearly, '2026-02-01')).toBe('2026-05-20')
  })

  it('solo los activos, del más cercano al más lejano, hasta tres', () => {
    const items = [
      item({ merchant: 'D', last_day: '2026-02-20', first_day: '2026-01-20' }),
      item({ merchant: 'A', last_day: '2026-01-08', first_day: '2025-12-08' }),
      item({ merchant: 'X', last_day: '2026-01-01', status: 'cancelado' }),
      item({ merchant: 'B', last_day: '2026-01-10', first_day: '2025-12-10' }),
      item({ merchant: 'C', last_day: '2026-01-12', first_day: '2025-12-12' }),
    ]
    expect(upcomingCharges(items, TODAY).map((c) => `${c.item.merchant} ${c.day}`)).toEqual([
      'A 2026-02-08',
      'B 2026-02-10',
      'C 2026-02-12',
    ])
  })

  it('el monto va en la moneda del cobro', () => {
    expect(chargeText(item())).toBe('US$ 11.99')
    expect(chargeText(item({ currency: 'DOP', typical_cents: 250_000 }))).toBe('RD$ 2,500')
  })
})

describe('recurrentes del hogar', () => {
  it('ofrece los grupos en el orden de la pantalla', () => {
    expect(GROUP_OPTIONS.map((g) => g.label)).toEqual([
      'Vivienda',
      'Préstamos',
      'Servicios',
      'Seguros',
      'Suscripciones',
      'Cargos del banco',
      'Otros recurrentes',
    ])
  })

  it('en un préstamo las cuotas se leen «quedan N»', () => {
    const loan = item({ group: 'Préstamos', group_key: 'prestamos', installments_left: 9 })
    expect(badgesOf(loan, null)).toEqual(['quedan 9'])
    expect(badgeTone('quedan 9')).toBe('positive')
    expect(badgesOf(item({ installments_left: 1 }), null)).toEqual(['1 cuota restante'])
  })

  it('dice los abonos extra del año solo si los hubo', () => {
    expect(extrasText(item({ extras_year_cents: 0 }))).toBeNull()
    expect(extrasText(item({ currency: 'DOP', extras_year_cents: 5_000_000 }))).toBe(
      'abonos extra este año: RD$ 50,000',
    )
  })

  it('lista los comercios de un proveedor o una unión', () => {
    expect(membersText(item())).toBeNull()
    const phone = item({
      merchant: 'proveedor:telfic',
      name: 'Telefónica Ficticia',
      members: ['TELFIC PAGO', 'TELFIC WB'],
    })
    expect(membersText(phone)).toBe('TELFIC PAGO, TELFIC WB')
  })

  it('une con los demás recurrentes y con los proveedores que no están, por nombre', () => {
    const water = item({ merchant: 'AGUA FICTICIA', name: 'AGUA FICTICIA', currency: 'DOP' })
    const phone = item({ merchant: 'proveedor:telfic', name: 'Telefónica Ficticia' })
    const phoneUsd = item({ merchant: 'proveedor:telfic', name: 'Telefónica Ficticia' })
    const data = {
      ...overview([water, phone, phoneUsd], []),
      providers: [
        { key: 'proveedor:telfic', name: 'Telefónica Ficticia' },
        { key: 'proveedor:luzfic', name: 'Luz Ficticia' },
      ],
    }
    expect(joinTargets(data, water)).toEqual([
      { key: 'proveedor:luzfic', name: 'Luz Ficticia' },
      { key: 'proveedor:telfic', name: 'Telefónica Ficticia' },
    ])
    expect(joinTargets(data, phone).map((t) => t.key)).toEqual([
      'AGUA FICTICIA',
      'proveedor:luzfic',
    ])
  })

  it('manda el grupo y las cuotas de «Es recurrente…» solo si se eligieron', () => {
    expect(txRecurringBody('mensual', '', null)).toEqual({ cadence: 'mensual' })
    expect(txRecurringBody('anual', 'vivienda', null)).toEqual({
      cadence: 'anual',
      group: 'vivienda',
    })
    expect(txRecurringBody('mensual', 'prestamos', 12)).toEqual({
      cadence: 'mensual',
      group: 'prestamos',
      installments_left: 12,
    })
  })
})

describe('grupo a mano y «Separar»', () => {
  it('el grupo elegido conserva la marca; vacío vuelve al de la categoría', () => {
    const marked = item({ mark: 'confirmed' })
    expect(groupBody(marked, 'vivienda')).toEqual({
      merchant: 'STREAMING FICTICIO',
      currency: 'USD',
      status: 'confirmed',
      group: 'vivienda',
    })
    expect(groupBody(marked, '').group).toBeNull()
  })

  it('no ofrece separar al comercio que da nombre a la serie', () => {
    expect(separableMembers(item())).toEqual([])
    const joined = item({ merchant: 'AGUA B', members: ['AGUA B', 'AGUA C'] })
    expect(separableMembers(joined)).toEqual(['AGUA C'])
    const phone = item({ merchant: 'proveedor:telfic', members: ['TELFIC PAGO', 'TELFIC WB'] })
    expect(separableMembers(phone)).toEqual(['TELFIC PAGO', 'TELFIC WB'])
  })
})
