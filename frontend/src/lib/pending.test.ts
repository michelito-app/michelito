import { describe, expect, it } from 'vitest'
import type { Pending, PendingItem } from './api'
import {
  ageText,
  isEmpty,
  itemAmount,
  itemMeta,
  netTone,
  pendingHref,
  pendingFigures,
  rateNote,
  unconvertedNote,
} from './pending'

function item(patch: Partial<PendingItem> = {}): PendingItem {
  const base: PendingItem = {
    kind: 'shared',
    fingerprint: 'f1',
    day: '2025-12-20',
    merchant: 'TIENDA INVENTADA',
    account_label: 'VISA ···4242',
    who: 'Luis',
    pending_cents: 400000,
    currency: 'DOP',
    pending_dop_cents: 400000,
    age_days: 39,
    rate: null,
    expense_count: 1,
    parts: [],
    ...patch,
  }
  const parts = patch.parts ?? [{ currency: base.currency, cents: base.pending_cents }]
  return { ...base, parts }
}

describe('grupos en Pendientes', () => {
  it('una fila por grupo: cuántos gastos y lo pendiente por moneda con ≈ RD$', () => {
    const group = item({
      merchant: 'Viaje Isla Ficticia',
      who: 'Carola y Rafael',
      expense_count: 2,
      parts: [
        { currency: 'DOP', cents: 600000 },
        { currency: 'USD', cents: 10000 },
      ],
      pending_dop_cents: 1220000,
    })
    expect(itemMeta(group)).toBe('20 dic 2025 · 2 gastos · Carola y Rafael · VISA ···4242')
    expect(itemAmount(group)).toEqual({
      main: 'RD$ 6,000 + US$ 100.00',
      approx: '≈ RD$ 12,200',
    })
  })

  it('si el título ya es «Con quién», no lo repite', () => {
    const group = item({ merchant: 'Carola', who: 'Carola' })
    expect(itemMeta(group)).toBe('20 dic 2025 · VISA ···4242')
  })
})

function pending(patch: Partial<Pending> = {}): Pending {
  return {
    owed_to_me_dop_cents: 1037000,
    i_owe_dop_cents: 1274000,
    net_dop_cents: -237000,
    unconverted_usd_cents: { owed_to_me: 0, i_owe: 0 },
    rate_month: '2026-02',
    rate: { value: '63.7000', month_used: '2026-02', source: 'bcrd' },
    owed_to_me: [item()],
    i_owe: [item({ kind: 'exchange', currency: 'USD', pending_cents: 20000 })],
    ...patch,
  }
}

describe('ageText', () => {
  it('cuenta los días desde la fecha', () => {
    expect(ageText(39)).toBe('hace 39 días')
    expect(ageText(1)).toBe('hace 1 día')
    expect(ageText(0)).toBe('hoy')
  })
})

describe('itemMeta', () => {
  it('fecha con año, para quién y cuenta', () => {
    expect(itemMeta(item())).toBe('20 dic 2025 · Luis · VISA ···4242')
    expect(itemMeta(item({ who: '' }))).toBe('20 dic 2025 · VISA ···4242')
  })
})

describe('itemAmount', () => {
  it('en pesos, solo el monto', () => {
    expect(itemAmount(item())).toEqual({ main: 'RD$ 4,000', approx: null })
  })

  it('en dólares, con lo que vale en pesos', () => {
    const usd = item({ currency: 'USD', pending_cents: 10000, pending_dop_cents: 637000, rate: '63.7000' })
    expect(itemAmount(usd)).toEqual({ main: 'US$ 100.00', approx: '≈ RD$ 6,370' })
  })

  it('un cambio dice a qué tasa se pactó', () => {
    const exchange = item({
      kind: 'exchange',
      currency: 'USD',
      pending_cents: 10000,
      pending_dop_cents: 588500,
      rate: '58.8500',
    })
    expect(itemAmount(exchange)).toEqual({ main: 'US$ 100.00', approx: '≈ RD$ 5,885 a 58.85' })
    const inPesos = item({ kind: 'exchange', rate: '60.0000' })
    expect(itemAmount(inPesos)).toEqual({ main: 'RD$ 4,000', approx: 'a 60.00' })
  })

  it('en dólares sin tasa, sin inventar', () => {
    const usd = item({ currency: 'USD', pending_cents: 10000, pending_dop_cents: null })
    expect(itemAmount(usd)).toEqual({ main: 'US$ 100.00', approx: null })
  })
})

describe('pendingFigures', () => {
  it('te deben, debes y neto en RD$', () => {
    expect(pendingFigures(pending())).toEqual([
      { key: 'owed', label: 'Te deben', value: 'RD$ 10,370', extra: null },
      { key: 'owe', label: 'Debes', value: 'RD$ 12,740', extra: null },
      { key: 'net', label: 'Neto', value: '−RD$ 2,370', extra: null },
    ])
  })

  it('los US$ sin tasa van aparte', () => {
    const figures = pendingFigures(
      pending({ unconverted_usd_cents: { owed_to_me: 10000, i_owe: 0 }, net_dop_cents: 0 }),
    )
    expect(figures[0]?.extra).toBe('+ US$ 100.00 sin tasa')
    expect(figures[1]?.extra).toBeNull()
    expect(figures[2]?.value).toBe('RD$ 0')
  })
})

describe('textos sueltos', () => {
  it('nota de US$ sin tasa', () => {
    expect(unconvertedNote(0)).toBeNull()
    expect(unconvertedNote(2550)).toBe('+ US$ 25.50 sin tasa')
  })

  it('el neto a favor, en contra o en cero', () => {
    expect(netTone(500)).toBe('favor')
    expect(netTone(-500)).toBe('contra')
    expect(netTone(0)).toBe('cero')
  })

  it('la tasa más reciente, solo si algún compartido en US$ la usó', () => {
    const hotel = item({ currency: 'USD', pending_cents: 3000, pending_dop_cents: 191100, rate: '63.7000' })
    expect(rateNote(pending({ owed_to_me: [hotel] }))).toBe(
      'Compartidos en US$ a la tasa de febrero 2026 (63.70)',
    )
    expect(rateNote(pending({ owed_to_me: [hotel], rate: null, rate_month: null }))).toBeNull()
    // Los cambios llevan su propia tasa en la fila.
    expect(rateNote(pending())).toBeNull()
    const noRate = item({ currency: 'USD', pending_dop_cents: null })
    expect(rateNote(pending({ owed_to_me: [noRate] }))).toBeNull()
  })

  it('el enlace lleva las cuentas elegidas', () => {
    expect(pendingHref(null)).toBe('/pendientes')
    expect(pendingHref(['a', 'b'])).toBe('/pendientes?cuentas=a%2Cb')
  })

  it('vacío: nadie te debe y no debes nada', () => {
    expect(isEmpty(pending())).toBe(false)
    expect(isEmpty(pending({ owed_to_me: [], i_owe: [] }))).toBe(true)
  })
})
