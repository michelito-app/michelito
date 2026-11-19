import { describe, expect, it } from 'vitest'
import type { SharedList, SharedListExpense, SharedListGroup } from './api'
import {
  chipCounts,
  dateRange,
  emptyText,
  excessText,
  expenseState,
  filterGroups,
  groupMatches,
  groupMeta,
  moneyLine,
  noneText,
  parseChip,
  parseGroup,
  refundLabel,
  sharedFigures,
  sharedParams,
  statusText,
  withPinned,
} from './sharedList'

function expense(patch: Partial<SharedListExpense> = {}): SharedListExpense {
  return {
    fingerprint: 'e1',
    day: '2026-02-03',
    merchant: 'HOTEL INVENTADO',
    account_label: 'VISA ···4242',
    amount_cents: 5950,
    currency: 'USD',
    people: 2,
    my_share_cents: null,
    for_other: false,
    share_cents: 2975,
    reimbursed_cents: 0,
    pending_cents: 2975,
    written_off_cents: 0,
    ...patch,
  }
}

function group(patch: Partial<SharedListGroup> = {}): SharedListGroup {
  return {
    id: 1,
    title: 'Viaje Isla Ficticia',
    name: 'Viaje Isla Ficticia',
    with_whom: 'Carola',
    status: 'pending',
    first_fingerprint: 'e1',
    first_day: '2026-02-03',
    last_day: '2026-02-07',
    last_activity: '2026-02-07',
    expenses: [expense(), expense({ fingerprint: 'e2', merchant: 'CINE FICTICIO' })],
    refunds: [],
    paid: [{ currency: 'USD', cents: 11900 }],
    reimbursed: [],
    pending: [{ currency: 'USD', cents: 2975 }],
    pending_dop_cents: 189508,
    unconverted_usd_cents: 0,
    excess: [],
    ...patch,
  }
}

const SETTLED = group({ id: 2, title: 'Luis', name: '', with_whom: 'Luis', status: 'settled' })
const LOST = group({ id: 3, title: 'Rosa', name: '', with_whom: 'Rosa', status: 'written_off' })

describe('textos de estado', () => {
  it('te deben en su moneda y, con US$, ≈ RD$ como Pendientes', () => {
    expect(statusText(group())).toEqual({ main: 'Te deben US$ 29.75', approx: '≈ RD$ 1,895' })
  })

  it('en pesos no lleva ≈; sin tasa tampoco', () => {
    const pesos = group({ pending: [{ currency: 'DOP', cents: 200000 }], pending_dop_cents: 200000 })
    expect(statusText(pesos)).toEqual({ main: 'Te deben RD$ 2,000', approx: null })
    expect(statusText(group({ pending_dop_cents: null })).approx).toBeNull()
  })

  it('US$ pendientes sin ninguna tasa: la nota en vez de ≈ RD$', () => {
    const none = group({ pending_dop_cents: null, unconverted_usd_cents: 2975 })
    expect(statusText(none)).toEqual({
      main: 'Te deben US$ 29.75',
      approx: '+ US$ 29.75 sin tasa',
    })
  })

  it('sin grupos: aún no hay compartidos o ninguno en las cuentas elegidas', () => {
    expect(emptyText(false)).toBe('Aún no tienes gastos compartidos')
    expect(emptyText(true)).toBe('Ningún grupo en las cuentas elegidas')
  })

  it('saldado y dado por perdido', () => {
    expect(statusText(SETTLED).main).toBe('Saldado')
    expect(statusText(LOST).main).toBe('Dado por perdido')
  })

  it('lo devuelto de más se avisa', () => {
    expect(excessText(group())).toBeNull()
    const over = group({ excess: [{ currency: 'DOP', cents: 30000 }] })
    expect(excessText(over)).toBe('Te devolvieron RD$ 300 de más')
  })

  it('cada gasto: saldado, pendiente o perdido', () => {
    expect(expenseState(expense())).toBe('Pendiente US$ 29.75')
    expect(expenseState(expense({ pending_cents: 0 }))).toBe('Saldado')
    expect(expenseState(expense({ pending_cents: 0, written_off_cents: 2975 }))).toBe(
      'Dado por perdido',
    )
  })

  it('la fila: con quién, cuántos gastos, fechas y lo pagado', () => {
    expect(groupMeta(group())).toBe('Carola · 2 gastos · 3 feb – 7 feb 2026')
    expect(groupMeta(SETTLED)).toBe('2 gastos · 3 feb – 7 feb 2026') // el título ya es «Luis»
    expect(moneyLine(group())).toBe('Pagaste US$ 119.00 · nada devuelto')
    const back = group({ reimbursed: [{ currency: 'DOP', cents: 217500 }] })
    expect(moneyLine(back)).toBe('Pagaste US$ 119.00 · te devolvieron RD$ 2,175')
  })

  it('fechas de un día, del mismo año y entre años', () => {
    expect(dateRange('2025-12-20', '2025-12-20')).toBe('20 dic 2025')
    expect(dateRange('2025-12-18', '2026-01-09')).toBe('18 dic 2025 – 9 ene 2026')
  })

  it('los reembolsos: el crédito y su cuenta, o «A mano»', () => {
    const base = { key: 'c1', day: '2026-02-04', amount_cents: 100000, currency: 'DOP' }
    const credit = { ...base, manual: false, description: 'TOKE DE ANA', account_label: 'Cta ···2' }
    expect(refundLabel(credit)).toBe('TOKE DE ANA · Cta ···2')
    const cash = { ...base, manual: true, description: 'Marta', account_label: '' }
    expect(refundLabel(cash)).toBe('A mano · Marta · efectivo')
    expect(refundLabel({ ...cash, description: '', account_label: 'Banco X' })).toBe(
      'A mano · Banco X',
    )
  })
})

describe('chips', () => {
  const all = [group(), SETTLED, LOST]

  it('filtran por estado; arranca en Todos', () => {
    expect(parseChip(null)).toBe('todos')
    expect(parseChip('otra-cosa')).toBe('todos')
    expect(filterGroups(all, 'todos', '').map((g) => g.id)).toEqual([1, 2, 3])
    expect(filterGroups(all, 'pendiente', '').map((g) => g.id)).toEqual([1])
    expect(filterGroups(all, 'saldados', '').map((g) => g.id)).toEqual([2])
    expect(filterGroups(all, 'perdidos', '').map((g) => g.id)).toEqual([3])
    expect(chipCounts(all)).toEqual({ todos: 3, pendiente: 1, saldados: 1, perdidos: 1 })
  })

  it('el grupo desplegado al volver sigue en la lista aunque ya no coincida, en su lugar', () => {
    const shown = filterGroups(all, 'saldados', '')
    expect(withPinned(all, shown, 1).map((g) => g.id)).toEqual([1, 2])
    expect(withPinned(all, shown, 2).map((g) => g.id)).toEqual([2])
    expect(withPinned(all, shown, null).map((g) => g.id)).toEqual([2])
    expect(withPinned(all, shown, 99).map((g) => g.id)).toEqual([2]) // ya no existe
  })

  it('sin resultados: «Ningún grupo <estado>»', () => {
    expect(noneText('saldados', '')).toBe('Ningún grupo saldado')
    expect(noneText('perdidos', '')).toBe('Ningún grupo perdido')
    expect(noneText('pendiente', ' ana ')).toBe('Ningún grupo con pendiente coincide con «ana»')
  })

  it('el chip, la búsqueda y el grupo van en la URL sin pisar las cuentas', () => {
    const current = new URLSearchParams('cuentas=visa')
    const next = sharedParams(current, { chip: 'saldados', query: 'ana', group: 4 })
    expect(next.toString()).toBe('cuentas=visa&estado=saldados&q=ana&grupo=4')
    expect(sharedParams(next, { chip: 'todos', query: '', group: null }).toString()).toBe(
      'cuentas=visa',
    )
    expect(parseGroup('4')).toBe(4)
    expect(parseGroup('x')).toBeNull()
  })
})

describe('buscador', () => {
  it('por nombre, «Con quién» o comercio de cualquier gasto, sin acentos', () => {
    expect(groupMatches(group(), 'isla')).toBe(true)
    expect(groupMatches(group(), 'CAROLA')).toBe(true)
    expect(groupMatches(group(), 'cine')).toBe(true)
    expect(groupMatches(group({ with_whom: 'Rocío' }), 'rocio')).toBe(true)
    expect(groupMatches(group(), 'farmacia')).toBe(false)
  })

  it('por monto, con las reglas del selector', () => {
    expect(groupMatches(group(), '59.5')).toBe(true) // un gasto
    expect(groupMatches(group(), 'US$ 29.75')).toBe(true) // lo pendiente
    expect(groupMatches(group(), '119')).toBe(true) // lo pagado
    expect(groupMatches(group(), '1,000')).toBe(false)
  })

  it('se combina con el chip', () => {
    expect(filterGroups([group(), SETTLED], 'saldados', 'isla')).toEqual([])
    expect(filterGroups([group(), SETTLED], 'todos', 'luis').map((g) => g.id)).toEqual([2])
  })
})

describe('totales', () => {
  it('te deben, lo devuelto este año y los abiertos; los US$ sin tasa aparte', () => {
    const list: SharedList = {
      owed_dop_cents: 400000,
      reimbursed_year_dop_cents: 217500,
      year: 2026,
      open_count: 1,
      unconverted: { owed_usd_cents: 2975, reimbursed_usd_cents: 0 },
      rate: null,
      groups: [],
    }
    expect(sharedFigures(list)).toEqual([
      { key: 'owed', label: 'Te deben', value: '≈ RD$ 4,000', extra: '+ US$ 29.75 sin tasa' },
      { key: 'year', label: 'Te devolvieron este año', value: '≈ RD$ 2,175', extra: null },
      { key: 'open', label: 'Abiertos', value: '1 grupo abierto', extra: null },
    ])
    expect(sharedFigures({ ...list, open_count: 3 })[2].value).toBe('3 grupos abiertos')
  })
})
