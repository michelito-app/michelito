import { describe, expect, it } from 'vitest'
import type { CashBox, CashLine, Tx } from './api'
import {
  approxText,
  balanceAfter,
  balanceText,
  cashBoxNote,
  cashBoxText,
  deleteWarning,
  depositBody,
  draftDelta,
  draftOfLine,
  emptyDraft,
  entryBody,
  isNegative,
  lastDay,
  lineAmount,
  lineDetail,
  lineHref,
  showCashBox,
  wouldBeNegative,
} from './cashBox'

function box(overrides: Partial<CashBox> = {}): CashBox {
  return {
    account_key: 'manual:caja-fuerte',
    label: 'Caja fuerte',
    exists: true,
    balances: [
      { currency: 'DOP', amount_cents: 500_000 },
      { currency: 'USD', amount_cents: 20_000 },
    ],
    total_dop_cents: 1_762_000,
    unconverted: [],
    negative: [],
    uncounted: [],
    lines: [],
    ...overrides,
  }
}

function line(overrides: Partial<CashLine> = {}): CashLine {
  return {
    kind: 'expense',
    day: '2026-01-20',
    fingerprint: 'caja-3',
    entry_id: 3,
    currency: 'DOP',
    amount_cents: -150_000,
    dop_cents: -150_000,
    source_amount_cents: 150_000,
    source_currency: 'DOP',
    merchant: 'CAJA FUERTE',
    account_label: 'Caja fuerte',
    category: 'Supermercado',
    category_id: 1,
    note: 'Colmado',
    in_flow: true,
    group: null,
    ...overrides,
  }
}

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f1',
    currency: 'DOP',
    can_store: false,
    can_deposit: false,
    cash_box_role: '',
    cash_box_currency: null,
    cash_box_amount_cents: null,
    ...overrides,
  } as Tx
}

describe('textos de la caja', () => {
  it('la línea del Resumen solo con retiros guardados', () => {
    expect(cashBoxNote(0)).toBeNull()
    expect(cashBoxNote(500_000)).toBe('de eso, RD$ 5,000 fueron a la caja fuerte')
  })

  it('saldo por moneda y ≈ RD$ con lo que no tiene tasa aparte', () => {
    expect(balanceText(box().balances)).toBe('RD$ 5,000 + US$ 200.00')
    expect(balanceText([])).toBe('RD$ 0')
    expect(approxText(box())).toBe('≈ RD$ 17,620')
    const without = box({ unconverted: [{ currency: 'USD', amount_cents: 5_000 }] })
    expect(approxText(without)).toBe('≈ RD$ 17,620 + US$ 50.00 sin tasa')
    expect(approxText(box({ balances: [{ currency: 'DOP', amount_cents: 1 }] }))).toBeNull()
  })

  it('avisa del saldo negativo sin bloquear', () => {
    expect(balanceAfter(box(), 'USD', -40_000)).toBe(-20_000)
    expect(balanceAfter(box(), 'USD', -10_000)).toBeNull()
    expect(balanceAfter(box(), 'EUR', -1)).toBe(-1)
    expect(wouldBeNegative('USD', -20_000)).toBe(
      'La caja quedaría en −US$ 200.00; ¿ajustar el saldo inicial?',
    )
    expect(isNegative({ currency: 'DOP', amount_cents: -850_000 })).toBe(
      'La caja está en −RD$ 8,500; ¿ajustar el saldo inicial?',
    )
  })

  it('monto y detalle de cada línea', () => {
    expect(lineAmount(line())).toBe('−RD$ 1,500')
    expect(lineAmount(line({ kind: 'stored', amount_cents: 2_000, currency: 'USD' }))).toBe(
      '+US$ 20.00',
    )
    const noRate = line({ kind: 'deposit', amount_cents: null, source_amount_cents: 600_000 })
    expect(lineAmount(noRate)).toBe('RD$ 6,000 (sin tasa)')
    expect(lineDetail(line())).toBe('Supermercado · Colmado')
    expect(lineHref(line({ fingerprint: 'caja-3' }))).toBe('/transacciones?mes=2026-01&tx=caja-3')
    const deposit = line({
      kind: 'deposit',
      currency: 'USD',
      amount_cents: -10_000,
      source_currency: 'DOP',
      source_amount_cents: 600_000,
      account_label: 'Ahorro ···999',
      note: '',
    })
    expect(lineDetail(deposit)).toBe('Ahorro ···999 · en el banco RD$ 6,000')
  })
})

describe('formularios', () => {
  it('arma el cuerpo de lo anotado o el error', () => {
    const draft = { ...emptyDraft('expense', '2026-01-20'), amount: '1,500.50', note: ' x ' }
    expect(entryBody(draft, '2026-02-07')).toEqual({
      kind: 'expense',
      day: '2026-01-20',
      amount_cents: 150_050,
      currency: 'DOP',
      category_id: null,
      note: 'x',
    })
    expect(entryBody({ ...draft, amount: '0' }, '2026-02-07')).toMatch(/monto/)
    expect(entryBody({ ...draft, day: '' }, '2026-02-07')).toMatch(/fecha/)
    expect(entryBody({ ...draft, day: '2062-01-20' }, '2026-02-07')).toBe(
      'La fecha va del 2000-01-01 al 2026-03-10',
    )
    expect(entryBody({ ...draft, day: '1999-12-31' }, '2026-02-07')).toMatch(/2000-01-01/)
    expect(lastDay('2026-12-15')).toBe('2027-01-15')
    const initial = {
      ...emptyDraft('initial', '2026-01-01'),
      amount: '200',
      currency: 'USD' as const,
    }
    expect(entryBody(initial, '2026-02-07')).toEqual({
      kind: 'initial',
      day: '2026-01-01',
      amount_cents: 20_000,
      currency: 'USD',
    })
  })

  it('el cambio de saldo de lo que se guarda (editar no cuenta lo anterior)', () => {
    const body = {
      kind: 'expense' as const,
      day: '2026-01-20',
      amount_cents: 200_000,
      currency: 'DOP' as const,
    }
    expect(draftDelta(body)).toBe(-200_000)
    expect(draftDelta(body, line())).toBe(-50_000)
    expect(draftDelta({ ...body, kind: 'income' })).toBe(200_000)
    expect(draftOfLine(line())).toMatchObject({ amount: '1500.00', categoryId: 1, note: 'Colmado' })
  })

  it('un depósito en otra moneda lleva la moneda y, si se dijo, el monto', () => {
    expect(depositBody(tx(), 'DOP', '50')).toEqual({})
    expect(depositBody(tx(), 'USD', '')).toEqual({ currency: 'USD' })
    expect(depositBody(tx(), 'USD', '98.50')).toEqual({ currency: 'USD', amount_cents: 9_850 })
    expect(depositBody(tx(), 'USD', 'x')).toMatch(/monto/)
  })
})

describe('detalle de una transacción', () => {
  it('dice qué pasa y cuándo se muestra', () => {
    expect(showCashBox(tx())).toBe(false)
    expect(showCashBox(tx({ can_store: true }))).toBe(true)
    expect(cashBoxText(tx({ can_store: true }))).toMatch(/no cuenta como gasto/)
    expect(cashBoxText(tx({ cash_box_role: 'stored' }))).toMatch(/^Guardado en la caja fuerte/)
    expect(cashBoxText(tx({ cash_box_role: 'deposit', cash_box_currency: 'DOP' }))).toBe(
      'Vino de la caja fuerte: no cuenta como ingreso.',
    )
    const usd = tx({
      cash_box_role: 'deposit',
      cash_box_currency: 'USD',
      cash_box_amount_cents: 10_000,
    })
    expect(cashBoxText(usd)).toBe(
      'Vino de la caja fuerte (salieron US$ 100.00 de la caja): no cuenta como ingreso.',
    )
    expect(cashBoxText({ ...usd, cash_box_amount_cents: null })).toMatch(/sin tasa/)
  })
})

describe('borrar', () => {
  it('avisa si sale de un grupo compartido', () => {
    expect(deleteWarning(null)).toBe(
      '¿Borrar este movimiento de la caja? Se borran también su nota y su categoría.',
    )
    expect(deleteWarning('Ana')).toMatch(
      /También sale de «Ana»; si es su único gasto, el grupo y sus reembolsos anotados se borran\.$/,
    )
  })
})
