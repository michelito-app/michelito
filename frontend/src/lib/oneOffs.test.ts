import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
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
import { shortAccountLabel } from './accounts'
import { shortDay } from './months'
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
    reasons: ['rarely used category', 'new merchant'],
    ...overrides,
  }
}

describe('cardTitle', () => {
  it('carries how many there are', () => {
    expect(cardTitle(3)).toBe(t('summary.oneOffs.cardTitle', { count: 3 }))
    expect(cardTitle(3)).toContain('(3)')
  })
})

describe('amountText', () => {
  it('in RD$; dollars carry the original', () => {
    expect(amountText(suggestion())).toBe('RD$ 45,000')
    expect(
      amountText(suggestion({ currency: 'USD', amount_cents: 20_000, amount_dop_cents: 1_200_000 })),
    ).toBe('RD$ 12,000 · US$ 200.00')
  })
})

describe('metaText', () => {
  it('day and account', () => {
    expect(metaText(suggestion())).toBe(`${shortDay('2026-02-06')} · VISA DEMO ···4242`)
  })

  it('a bank account goes with its short name', () => {
    const label = 'POPULAR Cuenta de ahorro 100200300' // spanish-data
    expect(metaText(suggestion({ account_label: label }))).toBe(
      `${shortDay('2026-02-06')} · ${shortAccountLabel(label)}`,
    )
    expect(shortAccountLabel(label)).not.toBe(label)
  })
})

describe('transactionHref', () => {
  it('opens the purchase month with its detail; the fingerprint is encoded', () => {
    expect(transactionHref(suggestion())).toBe('/transactions?month=2026-02&tx=abc%2F1')
  })

  it('Transactions reads it as that month and that row', () => {
    const href = transactionHref(suggestion())
    const filters = parseFilters(new URL(href, 'http://localhost').searchParams)
    expect(filters.month).toBe('2026-02')
    expect(filters.tx).toBe('abc/1')
  })

  it('carries the chosen accounts so the row is in the list', () => {
    expect(transactionHref(suggestion(), ['demo:credit_card'])).toBe(
      '/transactions?month=2026-02&tx=abc%2F1&accounts=demo%3Acredit_card',
    )
  })

  it('the month comes from the purchase day', () => {
    expect(transactionHref(suggestion({ day: '2025-10-16', fingerprint: 'f' }))).toBe(
      '/transactions?month=2025-10&tx=f',
    )
  })
})

describe('openLabel', () => {
  it('names the merchant, the amount and the full account', () => {
    const label = 'POPULAR Cuenta de ahorro 100200300' // spanish-data
    expect(openLabel(suggestion({ account_label: label }))).toBe(
      t('summary.oneOffs.openLabel', {
        merchant: 'AGENCIA DE VIAJES',
        amount: 'RD$ 45,000',
        when: `${shortDay('2026-02-06')} · ${label}`,
      }),
    )
  })
})

describe('dismissPath', () => {
  it('encodes the fingerprint', () => {
    expect(dismissPath('abc/1')).toBe('/api/one-off-suggestions/abc%2F1')
  })
})

describe('button labels', () => {
  it('name the merchant', () => {
    expect(confirmLabel(suggestion())).toBe(
      t('summary.oneOffs.confirmLabel', { merchant: 'AGENCIA DE VIAJES' }),
    )
    expect(dismissLabel(suggestion())).toBe(
      t('summary.oneOffs.dismissLabel', { merchant: 'AGENCIA DE VIAJES' }),
    )
  })
})
