import { describe, expect, it } from 'vitest'
import type { OneOffSuggestion } from './api'
import {
  amountText,
  cardTitle,
  confirmLabel,
  dismissLabel,
  dismissPath,
  metaText,
  openLabel,
  transactionHref,
} from './oneOffs'
import { parseFilters } from './transactions'

function suggestion(overrides: Partial<OneOffSuggestion> = {}): OneOffSuggestion {
  return {
    fingerprint: 'abc/1',
    day: '2026-02-06',
    merchant: 'AGENCIA DE VIAJES',
    description: 'AGENCIA DE VIAJES FICTICIA',
    account_label: 'VISA DEMO ···4242',
    amount_cents: 4_500_000,
    currency: 'DOP',
    amount_dop_cents: 4_500_000,
    reasons: ['categoría poco usada', 'comercio nuevo'],
    ...overrides,
  }
}

describe('cardTitle', () => {
  it('lleva cuántas hay', () => {
    expect(cardTitle(3)).toBe('Posibles gastos únicos (3)')
  })
})

describe('amountText', () => {
  it('en pesos; los dólares llevan el original', () => {
    expect(amountText(suggestion())).toBe('RD$ 45,000')
    expect(
      amountText(suggestion({ currency: 'USD', amount_cents: 20_000, amount_dop_cents: 1_200_000 })),
    ).toBe('RD$ 12,000 · US$ 200.00')
  })
})

describe('metaText', () => {
  it('día y cuenta', () => {
    expect(metaText(suggestion())).toBe('6 feb · VISA DEMO ···4242')
  })

  it('una cuenta bancaria va con su nombre corto', () => {
    expect(metaText(suggestion({ account_label: 'POPULAR Cuenta de ahorro 100200300' }))).toBe(
      '6 feb · Ahorro ···0300',
    )
  })
})

describe('transactionHref', () => {
  it('abre el mes de la compra con su detalle; la huella va codificada', () => {
    expect(transactionHref(suggestion())).toBe('/transacciones?mes=2026-02&tx=abc%2F1')
  })

  it('Transacciones lo lee como ese mes y esa fila', () => {
    const href = transactionHref(suggestion())
    const filters = parseFilters(new URL(href, 'http://localhost').searchParams)
    expect(filters.month).toBe('2026-02')
    expect(filters.tx).toBe('abc/1')
  })

  it('lleva las cuentas elegidas para que la fila esté en la lista', () => {
    expect(transactionHref(suggestion(), ['demo:credit_card'])).toBe(
      '/transacciones?mes=2026-02&tx=abc%2F1&cuentas=demo%3Acredit_card',
    )
  })

  it('el mes sale del día de la compra', () => {
    expect(transactionHref(suggestion({ day: '2025-10-16', fingerprint: 'f' }))).toBe(
      '/transacciones?mes=2025-10&tx=f',
    )
  })
})

describe('openLabel', () => {
  it('nombra el comercio, el monto y la cuenta completa', () => {
    const item = suggestion({ account_label: 'POPULAR Cuenta de ahorro 100200300' })
    expect(openLabel(item)).toBe(
      'Ver en Transacciones: AGENCIA DE VIAJES, RD$ 45,000, 6 feb · POPULAR Cuenta de ahorro 100200300',
    )
  })
})

describe('dismissPath', () => {
  it('codifica la huella', () => {
    expect(dismissPath('abc/1')).toBe('/api/one-off-suggestions/abc%2F1')
  })
})

describe('etiquetas de los botones', () => {
  it('nombran el comercio', () => {
    expect(confirmLabel(suggestion())).toBe('Es único: AGENCIA DE VIAJES')
    expect(dismissLabel(suggestion())).toBe('No es único: AGENCIA DE VIAJES')
  })
})
