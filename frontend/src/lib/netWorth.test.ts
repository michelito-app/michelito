import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { NetWorth, NetWorthHolding, NetWorthPoint } from './api'
import {
  changeLine,
  changeOf,
  holdingChange,
  isGood,
  loanNotice,
  pointsFor,
  shares,
  sideOf,
} from './netWorth'

function point(month: string, net: number): NetWorthPoint {
  return { month, day: `${month}-28`, net_cents: net, assets_cents: net, debts_cents: 0 }
}

function holding(extra: Partial<NetWorthHolding>): NetWorthHolding {
  return {
    key: 'k',
    label: 'K',
    group: 'banks',
    currency: 'DOP',
    value_cents: 0,
    value_dop_cents: 0,
    change_dop_cents: 0,
    ...extra,
  }
}

const HISTORY = ['2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02'].map((m, i) =>
  point(m, (i + 1) * 1000),
)

describe('pointsFor', () => {
  it('keeps the last month and the one before for 1M', () => {
    expect(pointsFor(HISTORY, '1M').map((p) => p.month)).toEqual(['2026-01', '2026-02'])
  })

  it('keeps four points for 3M', () => {
    expect(pointsFor(HISTORY, '3M')).toHaveLength(4)
  })

  it('keeps everything for ALL and when there is less history than asked', () => {
    expect(pointsFor(HISTORY, 'ALL')).toHaveLength(6)
    expect(pointsFor(HISTORY, '1A')).toHaveLength(6)
  })
})

describe('changeOf', () => {
  it('is the last net minus the first', () => {
    expect(changeOf(pointsFor(HISTORY, '3M'))).toBe(3000)
  })

  it('is null with fewer than two points', () => {
    expect(changeOf([point('2026-02', 5)])).toBeNull()
  })
})

describe('isGood', () => {
  it('a rise is good for an asset and bad for a debt', () => {
    expect(isGood(100, 'asset')).toBe(true)
    expect(isGood(100, 'debt')).toBe(false)
    expect(isGood(-100, 'debt')).toBe(true)
  })
})

describe('changeLine', () => {
  it('says the amount with an arrow and the period', () => {
    expect(changeLine(320_000)).toBe(t('accounts.change.month', { arrow: '↑', amount: 'RD$ 3,200' }))
    expect(changeLine(-5_000)).toBe(t('accounts.change.month', { arrow: '↓', amount: 'RD$ 50' }))
  })

  it('is nothing without a change', () => {
    expect(changeLine(0)).toBeNull()
    expect(changeLine(null)).toBeNull()
  })
})

describe('holdingChange', () => {
  it('adds the currencies of one account', () => {
    const found = holdingChange(
      [
        holding({ key: 'visa', change_dop_cents: 100 }),
        holding({ key: 'visa', currency: 'USD', change_dop_cents: 50 }),
        holding({ key: 'other', change_dop_cents: 7 }),
      ],
      'visa',
    )
    expect(found).toBe(150)
  })

  it('is null when no side is known', () => {
    expect(holdingChange([holding({ key: 'visa', change_dop_cents: null })], 'visa')).toBeNull()
    expect(holdingChange([], 'visa')).toBeNull()
  })
})

describe('shares', () => {
  const worth: NetWorth = {
    net_cents: 0,
    assets_cents: 300,
    debts_cents: 100,
    unconverted: false,
    groups: [
      { group: 'banks', side: 'asset', total_cents: 200 },
      { group: 'cash', side: 'asset', total_cents: 100 },
      { group: 'cards', side: 'debt', total_cents: 100 },
      { group: 'owed', side: 'asset', total_cents: 0 },
    ],
    holdings: [],
    history: [],
  }

  it('splits each side by group, largest first, leaving out empty ones', () => {
    expect(shares(worth, 'asset')).toEqual([
      { group: 'banks', total_cents: 200, share: 2 / 3 },
      { group: 'cash', total_cents: 100, share: 1 / 3 },
    ])
    expect(shares(worth, 'debt')).toEqual([{ group: 'cards', total_cents: 100, share: 1 }])
  })
})

describe('sideOf', () => {
  it('debts are cards, loans and what the user owes', () => {
    expect(sideOf('cards')).toBe('debt')
    expect(sideOf('owing')).toBe('debt')
    expect(sideOf('investments')).toBe('asset')
  })
})

describe('loanNotice', () => {
  const loan = { next_due: '2026-12-07', next_payment_cents: 775_666, currency: 'DOP' as const }

  it('warns when the installment is due within a week or so', () => {
    expect(loanNotice(loan, '2026-12-04')).toBe(
      t('accounts.row.loanDue', { amount: 'RD$ 7,757', when: t('accounts.due.inDays', { days: 3 }) }),
    )
  })

  it('says nothing when it is far or unknown', () => {
    expect(loanNotice(loan, '2026-11-23')).toBeNull()
    expect(loanNotice({ ...loan, next_due: null }, '2026-12-04')).toBeNull()
  })
})
