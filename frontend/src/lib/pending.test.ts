import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
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
import { monthPhrase, shortDay } from './months'

const DAY = `${shortDay('2025-12-20')} 2025`

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

describe('groups in Pending', () => {
  it('one row per group: how many expenses and what is pending per currency with ≈ RD$', () => {
    const group = item({
      merchant: 'Trip to a made-up island',
      who: 'Carola and Rafael',
      expense_count: 2,
      parts: [
        { currency: 'DOP', cents: 600000 },
        { currency: 'USD', cents: 10000 },
      ],
      pending_dop_cents: 1220000,
    })
    expect(itemMeta(group)).toBe(
      `${DAY} · ${t('pending.meta.expenses', { count: 2 })} · Carola and Rafael · VISA ···4242`,
    )
    expect(itemMeta(group)).toBe('20 dic 2025 · 2 gastos · Carola and Rafael · VISA ···4242') // spanish-ui
    expect(itemAmount(group)).toEqual({
      main: 'RD$ 6,000 + US$ 100.00',
      approx: t('pending.approx', { amount: 'RD$ 12,200' }),
    })
  })

  it('if the title already is "With whom", it does not repeat it', () => {
    const group = item({ merchant: 'Carola', who: 'Carola' })
    expect(itemMeta(group)).toBe(`${DAY} · VISA ···4242`)
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
  it('counts the days since the date', () => {
    expect(ageText(39)).toBe(t('pending.age.daysAgo', { count: 39 }))
    expect(ageText(1)).toBe(t('pending.age.daysAgo', { count: 1 }))
    expect(ageText(1)).toBe('hace 1 día') // spanish-ui
    expect(ageText(0)).toBe(t('pending.age.today'))
    expect(ageText(-1)).toBe(t('pending.age.today'))
  })
})

describe('itemMeta', () => {
  it('date with year, for whom and account', () => {
    expect(itemMeta(item())).toBe(`${DAY} · Luis · VISA ···4242`)
    expect(itemMeta(item({ who: '' }))).toBe(`${DAY} · VISA ···4242`)
  })
})

describe('itemAmount', () => {
  it('in RD$, only the amount', () => {
    expect(itemAmount(item())).toEqual({ main: 'RD$ 4,000', approx: null })
  })

  it('in dollars, with what it is worth in RD$', () => {
    const usd = item({ currency: 'USD', pending_cents: 10000, pending_dop_cents: 637000, rate: '63.7000' })
    expect(itemAmount(usd)).toEqual({
      main: 'US$ 100.00',
      approx: t('pending.approx', { amount: 'RD$ 6,370' }),
    })
  })

  it('an exchange says at which rate it was agreed', () => {
    const exchange = item({
      kind: 'exchange',
      currency: 'USD',
      pending_cents: 10000,
      pending_dop_cents: 588500,
      rate: '58.8500',
    })
    expect(itemAmount(exchange)).toEqual({
      main: 'US$ 100.00',
      approx: `${t('pending.approx', { amount: 'RD$ 5,885' })} ${t('pending.agreedRate', { rate: '58.85' })}`,
    })
    const inDop = item({ kind: 'exchange', rate: '60.0000' })
    expect(itemAmount(inDop)).toEqual({
      main: 'RD$ 4,000',
      approx: t('pending.agreedRate', { rate: '60.00' }),
    })
  })

  it('in dollars without a rate, without making anything up', () => {
    const usd = item({ currency: 'USD', pending_cents: 10000, pending_dop_cents: null })
    expect(itemAmount(usd)).toEqual({ main: 'US$ 100.00', approx: null })
  })
})

describe('pendingFigures', () => {
  it('owed to you, you owe and net in RD$', () => {
    expect(pendingFigures(pending())).toEqual([
      { key: 'owed', label: t('pending.figure.owed'), value: 'RD$ 10,370', extra: null },
      { key: 'owe', label: t('pending.figure.owe'), value: 'RD$ 12,740', extra: null },
      { key: 'net', label: t('pending.figure.net'), value: '−RD$ 2,370', extra: null },
    ])
  })

  it('US$ without a rate go apart', () => {
    const figures = pendingFigures(
      pending({ unconverted_usd_cents: { owed_to_me: 10000, i_owe: 0 }, net_dop_cents: 0 }),
    )
    expect(figures[0]?.extra).toBe(t('pending.unconverted', { amount: 'US$ 100.00' }))
    expect(figures[1]?.extra).toBeNull()
    expect(figures[2]?.value).toBe('RD$ 0')
  })
})

describe('loose texts', () => {
  it('note of US$ without a rate', () => {
    expect(unconvertedNote(0)).toBeNull()
    expect(unconvertedNote(2550)).toBe(t('pending.unconverted', { amount: 'US$ 25.50' }))
    expect(unconvertedNote(2550)).toBe('+ US$ 25.50 sin tasa') // spanish-ui
  })

  it('the net in your favor, against you or at zero', () => {
    expect(netTone(500)).toBe('positive')
    expect(netTone(-500)).toBe('negative')
    expect(netTone(0)).toBe('zero')
  })

  it('the latest rate, only if a shared expense in US$ used it', () => {
    const hotel = item({ currency: 'USD', pending_cents: 3000, pending_dop_cents: 191100, rate: '63.7000' })
    expect(rateNote(pending({ owed_to_me: [hotel] }))).toBe(
      t('pending.rateNote', { month: monthPhrase('2026-02'), value: '63.70' }),
    )
    expect(rateNote(pending({ owed_to_me: [hotel], rate: null, rate_month: null }))).toBeNull()
    // Exchanges carry their own rate on the row.
    expect(rateNote(pending())).toBeNull()
    const noRate = item({ currency: 'USD', pending_dop_cents: null })
    expect(rateNote(pending({ owed_to_me: [noRate] }))).toBeNull()
  })

  it('the link carries the chosen accounts', () => {
    expect(pendingHref(null)).toBe('/pending')
    expect(pendingHref(['a', 'b'])).toBe('/pending?accounts=a%2Cb')
  })

  it('empty: nobody owes you and you owe nothing', () => {
    expect(isEmpty(pending())).toBe(false)
    expect(isEmpty(pending({ owed_to_me: [], i_owe: [] }))).toBe(true)
  })
})
