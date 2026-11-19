import { describe, expect, it } from 'vitest'
import type { Investment, InvestmentEntry, InvestmentList, Tx } from './api'
import {
  chipCounts,
  entryRole,
  excessWarning,
  filterInvestments,
  investedNote,
  investmentFigures,
  investmentMeta,
  investmentParams,
  investmentStats,
  noneText,
  parseChip,
  parseOpen,
  rateText,
  roleBody,
  unconvertedWarning,
  withPinned,
} from './investments'
import { categoryLocked, linkBadges, linkSummaries, listPath, showInvestment } from './links'

function entry(overrides: Partial<InvestmentEntry> = {}): InvestmentEntry {
  return {
    fingerprint: 'a1',
    day: '2025-12-02',
    merchant: 'MB A 0000000066',
    description: 'MB a 0000000066 PEDRO INVERSOR FICTICIO',
    account_label: 'Ahorro ···888',
    role: 'contribution',
    amount_cents: 30_000_000,
    currency: 'DOP',
    capital_cents: 0,
    return_cents: 0,
    excess_cents: 0,
    counted: true,
    ...overrides,
  }
}

function investment(overrides: Partial<Investment> = {}): Investment {
  return {
    id: 1,
    title: 'Negocio de Pedro',
    name: 'Negocio de Pedro',
    with_whom: 'Pedro',
    status: 'active',
    currency: 'DOP',
    first_fingerprint: 'a1',
    pending_cents: 25_000_000,
    written_off: false,
    first_day: '2025-12-02',
    last_activity: '2025-12-29',
    last_credit: '2025-12-29',
    contributed_cents: 30_000_000,
    capital_returned_cents: 5_000_000,
    returns_cents: 1_900_000,
    excess_cents: 0,
    annual_rate: 0.125,
    pending_dop_cents: 25_000_000,
    unconverted_count: 0,
    entries: [
      entry(),
      entry({
        fingerprint: 'm1',
        day: '2025-12-29',
        merchant: 'TRANSF PEDRO INVERSOR',
        role: 'mixed',
        amount_cents: 6_000_000,
        capital_cents: 5_000_000,
        return_cents: 1_000_000,
      }),
    ],
    ...overrides,
  }
}

const closed = investment({
  id: 2,
  title: 'Préstamo a Ana',
  name: 'Préstamo a Ana',
  with_whom: 'Ana',
  status: 'closed',
  pending_cents: 0,
  contributed_cents: 5_000_000,
  capital_returned_cents: 5_000_000,
  returns_cents: 200_000,
  entries: [entry({ fingerprint: 'l1', merchant: 'MB A 0000000077', amount_cents: 5_000_000 })],
})
const lost = investment({ id: 3, title: 'Cripto', with_whom: '', status: 'written_off' })

describe('chips y buscador', () => {
  it('la URL elige el chip (por defecto «Activas») y la desplegada', () => {
    expect(parseChip(null)).toBe('activas')
    expect(parseChip('cerradas')).toBe('cerradas')
    expect(parseChip('otro')).toBe('activas')
    expect(parseOpen('12')).toBe(12)
    expect(parseOpen('x')).toBeNull()
  })

  it('«Cerradas» junta las cerradas y las dadas por perdidas', () => {
    const all = [investment(), closed, lost]
    expect(filterInvestments(all, 'activas', '').map((i) => i.id)).toEqual([1])
    expect(filterInvestments(all, 'cerradas', '').map((i) => i.id)).toEqual([2, 3])
    expect(chipCounts(all)).toEqual({ activas: 1, cerradas: 2, todas: 3 })
  })

  it('busca por nombre, con quién, comercio o monto, sin acentos', () => {
    const all = [investment(), closed]
    expect(filterInvestments(all, 'todas', 'prestamo').map((i) => i.id)).toEqual([2])
    expect(filterInvestments(all, 'todas', 'pedro').map((i) => i.id)).toEqual([1])
    expect(filterInvestments(all, 'todas', '300,000').map((i) => i.id)).toEqual([1])
    expect(noneText('activas', 'zzz')).toBe('Ninguna inversión activa coincide con «zzz»')
  })

  it('la desplegada al volver sigue en la lista aunque no coincida', () => {
    const all = [investment(), closed]
    expect(withPinned(all, [investment()], 2).map((i) => i.id)).toEqual([1, 2])
    expect(withPinned(all, [investment()], null).map((i) => i.id)).toEqual([1])
  })

  it('los parámetros quitan los valores por defecto y conservan las cuentas', () => {
    const current = new URLSearchParams('accounts=a&estado=cerradas')
    expect(investmentParams(current, { chip: 'activas', open: 2 }).toString()).toBe(
      'accounts=a&inversion=2',
    )
  })
})

describe('textos', () => {
  it('las cifras van en la moneda de la inversión y el % con un decimal', () => {
    const stats = Object.fromEntries(investmentStats(investment()).map((s) => [s.key, s.value]))
    expect(stats).toEqual({
      contributed: 'RD$ 300,000',
      returned: 'RD$ 50,000',
      pending: 'RD$ 250,000',
      returns: 'RD$ 19,000',
      rate: '12.5 %',
    })
    expect(rateText(null)).toBe('—')
    expect(rateText(0)).toBe('0.0 %')
  })

  it('la línea de fechas dice con quién, desde cuándo y el último cobro', () => {
    expect(investmentMeta(investment())).toBe(
      'Pedro · 2 dic – 29 dic 2025 · último cobro 29 dic 2025',
    )
    expect(investmentMeta(investment({ last_credit: null }))).toContain('sin cobros')
  })

  it('un mixto dice cuánto es capital y cuánto rendimiento', () => {
    expect(entryRole(investment().entries[1])).toBe(
      'Mixto: RD$ 50,000 de capital + RD$ 10,000 de rendimiento',
    )
    expect(entryRole(entry({ role: 'return' }))).toBe('Rendimiento')
  })

  it('avisa del capital devuelto de más: cuenta como rendimiento', () => {
    expect(excessWarning(investment())).toBeNull()
    expect(excessWarning(investment({ excess_cents: 5_000_000 }))).toBe(
      'Devolvieron RD$ 50,000 más de lo aportado; cuenta como rendimiento',
    )
    expect(entryRole(entry({ role: 'capital', excess_cents: 5_000_000 }))).toBe(
      'Devolución de capital (RD$ 50,000 de más: rendimiento)',
    )
  })

  it('avisa de lo que no suma por falta de tasa', () => {
    expect(unconvertedWarning(investment())).toBeNull()
    expect(unconvertedWarning(investment({ unconverted_count: 2 }))).toContain('2 movimientos')
  })

  it('las cifras de arriba van en ≈ RD$ y los US$ sin tasa aparte', () => {
    const list: InvestmentList = {
      pending_dop_cents: 25_000_000,
      returns_year_dop_cents: 2_100_000,
      year: 2026,
      active_count: 1,
      unconverted: { pending_usd_cents: 0, returns_usd_cents: 1_000 },
      rate: null,
      investments: [investment()],
    }
    expect(investmentFigures(list).map((f) => [f.value, f.extra])).toEqual([
      ['≈ RD$ 250,000', null],
      ['≈ RD$ 21,000', '+ US$ 10.00 sin tasa'],
      ['1 activa', null],
    ])
  })

  it('la línea del Resumen solo sale con aportes en el mes', () => {
    expect(investedNote(0)).toBeNull()
    expect(investedNote(30_000_000)).toBe('de eso, RD$ 300,000 fueron a inversiones')
  })
})

describe('tipo de un crédito', () => {
  it('un mixto pide 0 < capital < crédito', () => {
    expect(roleBody('return', '', 6_000_000)).toEqual({ body: { role: 'return' } })
    expect(roleBody('mixed', '50,000', 6_000_000)).toEqual({
      body: { role: 'mixed', capital_cents: 5_000_000 },
    })
    expect(roleBody('mixed', '60000', 6_000_000)).toHaveProperty('error')
    expect(roleBody('mixed', '0', 6_000_000)).toHaveProperty('error')
    expect(roleBody('mixed', 'abc', 6_000_000)).toHaveProperty('error')
  })
})

function tx(overrides: Partial<Tx>): Tx {
  return {
    link: '',
    can_share: false,
    can_reimburse: false,
    can_exchange: false,
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
    shared: null,
    exchange: null,
    suggested_group: null,
    suggested_exchange_with: null,
    pending_cents: 0,
    ...overrides,
  } as Tx
}

describe('la fila y el detalle', () => {
  it('un débito ofrece «Es una inversión…» y un crédito «Es de una inversión…»', () => {
    const [debit] = linkSummaries(tx({ can_invest: true }))
    expect([debit.kind, debit.action]).toEqual(['investment', 'Es una inversión…'])
    const [credit] = linkSummaries(tx({ can_invest_credit: true }))
    expect(credit.action).toBe('Es de una inversión…')
    expect(showInvestment(tx({}))).toBe(false)
  })

  it('uno enlazado dice su tipo, se gestiona y su categoría la manda el vínculo', () => {
    const ref = { ...investment(), kind: 'cobro_posible' as const }
    const linked = tx({ link: 'investment', investment: ref, investment_role: 'mixed' })
    const [summary] = linkSummaries(linked)
    expect([summary.text, summary.action]).toEqual(['Mixto de Negocio de Pedro', 'Gestionar…'])
    expect(categoryLocked(linked)).toBe(true)
    expect(linkBadges(linked).map((b) => b.label)).toEqual(['Inversión'])
    expect(linkBadges(tx({ suggested_investment: ref })).map((b) => b.label)).toEqual([
      '¿Inversión?',
    ])
  })

  it('«Volver» regresa a Inversiones tal cual', () => {
    expect(listPath('/inversiones?estado=cerradas&inversion=2')).toBe(
      '/inversiones?estado=cerradas&inversion=2',
    )
  })
})
