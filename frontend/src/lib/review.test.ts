import { describe, expect, it } from 'vitest'
import type { ReviewItem } from './api'
import {
  amountText,
  cardTitle,
  itemHref,
  itemKey,
  KIND_LABELS,
  mainAmountText,
  metaText,
  openLabel,
  originalAmountText,
  REVIEW_KINDS,
  reviewedLabel,
  reviewPath,
} from './review'

const TRANSFER: ReviewItem = {
  kind: 'tercero_grande',
  fingerprint: 'a/b c',
  day: '2026-02-13',
  month: '2026-02',
  merchant: 'TRANSFERENCIA A PERSONA',
  description: 'TRANSFERENCIA A PERSONA FICTICIA',
  account_label: 'FICTICIO Cuenta corriente 777-0',
  amount_cents: 100_000,
  currency: 'USD',
  amount_dop_cents: 6_370_000,
  reason: 'Transferencia a terceros de RD$ 63,700',
  reviewed: false,
}

describe('para revisar', () => {
  it('título y tipos', () => {
    expect(cardTitle(3)).toBe('Para revisar (3)')
    expect(REVIEW_KINDS).toEqual([
      'unico',
      'ingreso_inusual',
      'tercero_grande',
      'duplicado',
      'subio',
      'aporte_posible',
      'cobro_posible',
      'regla_posible',
      'reserva_posible',
    ])
    expect(KIND_LABELS.duplicado).toBe('¿Cargo duplicado?')
  })

  it('monto en RD$ y, si fue en dólares, también el original', () => {
    expect(amountText(TRANSFER)).toBe('RD$ 63,700 · US$ 1,000.00')
    expect(amountText({ ...TRANSFER, amount_dop_cents: null })).toBe('US$ 1,000.00')
    expect(amountText({ ...TRANSFER, currency: 'DOP', amount_cents: 500_000 })).toBe('RD$ 5,000')
  })

  it('en la fila corta: RD$ arriba y los US$ originales aparte', () => {
    expect(mainAmountText(TRANSFER)).toBe('RD$ 63,700')
    expect(originalAmountText(TRANSFER)).toBe('US$ 1,000.00')
    expect(mainAmountText({ ...TRANSFER, amount_dop_cents: null })).toBe('US$ 1,000.00')
    expect(originalAmountText({ ...TRANSFER, amount_dop_cents: null })).toBeNull()
    const pesos = { ...TRANSFER, currency: 'DOP', amount_cents: 500_000 }
    expect(mainAmountText(pesos)).toBe('RD$ 5,000')
    expect(originalAmountText(pesos)).toBeNull()
  })

  it('fecha y cuenta corta', () => {
    expect(metaText(TRANSFER)).toBe('13 feb · Corriente ···7770')
    expect(openLabel(TRANSFER)).toBe(
      'Ver en Transacciones: TRANSFERENCIA A PERSONA, RD$ 63,700 · US$ 1,000.00, 13 feb · FICTICIO Cuenta corriente 777-0',
    )
  })

  it('enlaces y rutas', () => {
    expect(itemHref(TRANSFER, ['k'])).toBe('/transacciones?mes=2026-02&tx=a%2Fb+c&cuentas=k')
    expect(reviewPath('duplicado', 'a/b c')).toBe('/api/review/duplicado/a%2Fb%20c')
    expect(itemKey(TRANSFER)).toBe('tercero_grande:a/b c')
  })

  it('el botón de un gasto único es «No es único»', () => {
    expect(reviewedLabel(TRANSFER)).toBe('Ya lo revisé: TRANSFERENCIA A PERSONA')
    expect(reviewedLabel({ ...TRANSFER, kind: 'unico' })).toBe('No es único: TRANSFERENCIA A PERSONA')
  })
})
