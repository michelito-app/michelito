import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
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
    category: 'Digital subscriptions',
    group: 'Subscriptions',
    cadence: 'monthly',
    status: 'active',
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
    group_key: 'subscriptions',
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

const ROSE = t('recurring.badge.rose')
const NEW = t('recurring.badge.new')
const CANCELLED = t('recurring.badge.cancelled')
const INACTIVE = t('recurring.badge.inactive')
const ENDED = t('recurring.badge.ended')
const CHARGED_AGAIN = t('recurring.badge.chargedAgain')
const VARIABLE = t('recurring.badge.variable')
const left = (count: number) => t('recurring.badge.installmentsLeft', { count })

describe('badgesOf', () => {
  it('puts no badges on an active item without changes', () => {
    expect(badgesOf(item(), '2026-02')).toEqual([])
  })

  it('marks "went up" only when the price rises', () => {
    const up = { before_cents: 999, after_cents: 1199, day: '2026-02-05' }
    const down = { before_cents: 1199, after_cents: 999, day: '2026-02-05' }
    expect(badgesOf(item({ price_change: up }), '2026-02')).toEqual([ROSE])
    expect(badgesOf(item({ price_change: down }), '2026-02')).toEqual([])
  })

  it('marks "new" when the first charge falls in the reference month', () => {
    expect(badgesOf(item({ first_day: '2026-02-03' }), '2026-02')).toEqual([NEW])
    expect(badgesOf(item({ first_day: '2026-02-03' }), null)).toEqual([])
  })

  it('does not mark "new" in the first month with data', () => {
    const first = item({ first_day: '2025-12-03' })
    expect(badgesOf(first, '2025-12', '2025-12')).toEqual([])
    expect(badgesOf(first, '2025-12', '2025-11')).toEqual([NEW])
  })

  it('"went up" only in the month of the change, and "new"/"went up" only on active items', () => {
    const up = { before_cents: 999, after_cents: 1199, day: '2026-01-05' }
    expect(badgesOf(item({ price_change: up }), '2026-02')).toEqual([])
    const cancelled = item({
      price_change: { ...up, day: '2026-02-05' },
      status: 'cancelled',
    })
    expect(badgesOf(cancelled, '2026-02')).toEqual([CANCELLED])
    expect(badgesOf(item({ first_day: '2026-02-03', status: 'inactive' }), '2026-02')).toEqual([
      INACTIVE,
    ])
  })

  it('flags the charge after cancelling before the status', () => {
    const cancelled = item({
      status: 'cancelled',
      mark: 'cancelled',
      charged_after_cancel: true,
    })
    expect(badgesOf(cancelled, null)).toEqual([CHARGED_AGAIN, CANCELLED])
  })

  it('includes variable amounts, installments and statuses', () => {
    expect(badgesOf(item({ variable: true }), null)).toEqual([VARIABLE])
    expect(badgesOf(item({ installments_left: 4 }), null)).toEqual([left(4)])
    expect(badgesOf(item({ installments_left: 4 }), null)).toEqual(['4 cuotas restantes']) // spanish-ui
    expect(badgesOf(item({ installments_left: 1 }), null)).toEqual(['1 cuota restante']) // spanish-ui
    expect(badgesOf(item({ installments_left: 0, status: 'ended' }), null)).toEqual([ENDED])
    expect(badgesOf(item({ status: 'inactive' }), null)).toEqual([INACTIVE])
  })
})

describe('badgeTone', () => {
  it('uses the alert tone for rises and charges after cancelling', () => {
    expect(badgeTone(ROSE)).toBe('up')
    expect(badgeTone(CHARGED_AGAIN)).toBe('up')
  })

  it('tells installments, switched-off statuses and the neutral ones apart', () => {
    expect(badgeTone(left(3))).toBe('positive')
    expect(badgeTone(left(1))).toBe('positive')
    expect(badgeTone(INACTIVE)).toBe('muted')
    expect(badgeTone(CANCELLED)).toBe('muted')
    expect(badgeTone(ENDED)).toBe('muted')
    expect(badgeTone(NEW)).toBe('neutral')
    expect(badgeTone(VARIABLE)).toBe('neutral')
    expect(badgeTone('3 items')).toBe('neutral')
  })
})

describe('alertTone', () => {
  it('raises the tone of rises and charges after cancelling; "new" is neutral', () => {
    expect(alertTone('price_up')).toBe('up')
    expect(alertTone('charged_after_cancel')).toBe('up')
    expect(alertTone('new')).toBe('neutral')
  })
})

describe('row texts', () => {
  it('cadenceText says monthly or yearly', () => {
    expect(cadenceText(item())).toBe(t('recurring.cadence.monthly'))
    expect(cadenceText(item({ cadence: 'yearly' }))).toBe(t('recurring.cadence.yearly'))
  })

  it('sinceText uses the short month and a two-digit year', () => {
    expect(sinceText(item())).toBe(t('recurring.since', { month: 'dic', year: '25' })) // spanish-ui
    expect(sinceText(item())).toBe('desde dic 25') // spanish-ui
  })

  it('lastChargeText uses the day and the short month', () => {
    expect(lastChargeText(item())).toBe(t('recurring.lastCharge', { day: '5 feb' }))
  })
})

describe('costLines', () => {
  it('a monthly US$ charge shows RD$ and the original', () => {
    expect(costLines(item())).toEqual({
      main: 'RD$ 764',
      detail: t('recurring.cost.perMonthAmount', { amount: 'US$ 11.99' }),
    })
  })

  it('a monthly RD$ charge only says "per month"', () => {
    const gym = item({
      currency: 'DOP',
      typical_cents: 250000,
      monthly_cents: 250000,
    })
    expect(costLines(gym)).toEqual({ main: 'RD$ 2,500', detail: t('recurring.cost.perMonth') })
  })

  it('a yearly one shows the original charge per year', () => {
    const yearly = item({
      currency: 'DOP',
      cadence: 'yearly',
      typical_cents: 360000,
      monthly_cents: 30000,
    })
    expect(costLines(yearly)).toEqual({
      main: 'RD$ 300',
      detail: t('recurring.cost.perYear', { amount: 'RD$ 3,600' }),
    })
  })

  it('without a rate, a US$ charge is shown in its currency', () => {
    expect(costLines(item({ monthly_cents: null, yearly_cents: null }))).toEqual({
      main: 'US$ 11.99',
      detail: t('recurring.cost.perMonthNoRate'),
    })
  })

  it('a variable amount says it is an average', () => {
    const power = item({
      currency: 'DOP',
      variable: true,
      monthly_cents: 310000,
    })
    expect(costLines(power)).toEqual({
      main: 'RD$ 3,100',
      detail: t('recurring.cost.averagePerMonth'),
    })
  })
})

describe('totalLine', () => {
  it('joins the monthly and the yearly total', () => {
    expect(totalLine(326376, 3916516)).toBe('RD$ 3,264 al mes · RD$ 39,165 al año') // spanish-ui
  })
})

describe('sections', () => {
  it('groups in API order and leaves switched-off items at the end of their group', () => {
    const off = item({ merchant: 'OLD', status: 'inactive' })
    const on = item({ merchant: 'NEW' })
    const gym = item({ merchant: 'GYM', group: 'Other recurring' })
    const result = sections(
      overview([off, on, gym], [total('Subscriptions', 76376), total('Other recurring', 2500)]),
    )
    expect(result.map((s) => s.group)).toEqual(['Subscriptions', 'Other recurring'])
    expect(result[0].items.map((i) => i.merchant)).toEqual(['NEW', 'OLD'])
    expect(result[0].total?.monthly_cents).toBe(76376)
  })

  it('a group without active items has no total', () => {
    const result = sections(overview([item({ status: 'cancelled' })], []))
    expect(result[0].total).toBeNull()
  })
})

describe('mark bodies', () => {
  it('statusBody does not send the installments', () => {
    expect(statusBody(item(), 'dismissed')).toEqual({
      merchant: 'STREAMING FICTICIO',
      currency: 'USD',
      status: 'dismissed',
    })
  })

  it('installmentsBody keeps the current mark and sends explicit installments', () => {
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
  it('accepts integers from 0 to 600', () => {
    expect(parseInstallments('0')).toBe(0)
    expect(parseInstallments(' 12 ')).toBe(12)
    expect(parseInstallments('600')).toBe(600)
  })

  it('rejects empty text, decimals, negatives and more than 600', () => {
    for (const text of ['', '1.5', '-1', '601', 'twelve']) expect(parseInstallments(text)).toBeNull()
  })
})

describe('cardNote', () => {
  it('without recurring items says so instead of "RD$ 0 per month"', () => {
    expect(cardNote(overview([], []))).toBe(t('recurring.card.none'))
  })

  it('with recurring items and no alerts says there were no changes', () => {
    expect(cardNote(overview([item()], []))).toBe(t('recurring.card.noChanges'))
  })

  it('with alerts there is no note', () => {
    const data = {
      ...overview([item()], []),
      alerts: [
        {
          kind: 'price_up' as const,
          merchant: 'X',
          currency: 'USD',
          detail: 'Went up',
          name: 'X',
        },
      ],
    }
    expect(cardNote(data)).toBeNull()
  })
})

describe('upcoming charges', () => {
  const TODAY = '2026-02-01'

  it("the next one is a month (or a year) later, without passing the month's end", () => {
    const at = (first_day: string, last_day: string, cadence: 'monthly' | 'yearly' = 'monthly') =>
      nextChargeDay({ first_day, last_day, cadence }, '2000-01-01')
    expect(at('2025-12-05', '2026-02-05')).toBe('2026-03-05')
    expect(at('2025-12-31', '2026-01-31')).toBe('2026-02-28')
    expect(at('2025-11-15', '2025-12-15')).toBe('2026-01-15')
    expect(at('2023-02-28', '2024-02-29', 'yearly')).toBe('2025-02-28')
  })

  it('uses the typical day, not the one cut short by a short month', () => {
    expect(typicalDay({ first_day: '2025-12-31', last_day: '2026-02-28' })).toBe(31)
    expect(typicalDay({ first_day: '2025-12-05', last_day: '2026-02-08' })).toBe(8)
    expect(typicalDay({ first_day: '2025-12-15', last_day: '2026-02-28' })).toBe(28)
    const late = { first_day: '2025-12-31', last_day: '2026-02-28', cadence: 'monthly' as const }
    expect(nextChargeDay(late, '2026-03-01')).toBe('2026-03-31')
  })

  it('steps forward until it is not before today', () => {
    const old = { first_day: '2025-06-10', last_day: '2025-09-10', cadence: 'monthly' as const }
    expect(nextChargeDay(old, '2026-02-11')).toBe('2026-03-10')
    expect(nextChargeDay(old, '2026-02-10')).toBe('2026-02-10')
    const yearly = { first_day: '2023-05-20', last_day: '2024-05-20', cadence: 'yearly' as const }
    expect(nextChargeDay(yearly, '2026-02-01')).toBe('2026-05-20')
  })

  it('only active ones, nearest first, up to three', () => {
    const items = [
      item({ merchant: 'D', last_day: '2026-02-20', first_day: '2026-01-20' }),
      item({ merchant: 'A', last_day: '2026-01-08', first_day: '2025-12-08' }),
      item({ merchant: 'X', last_day: '2026-01-01', status: 'cancelled' }),
      item({ merchant: 'B', last_day: '2026-01-10', first_day: '2025-12-10' }),
      item({ merchant: 'C', last_day: '2026-01-12', first_day: '2025-12-12' }),
    ]
    expect(upcomingCharges(items, TODAY).map((c) => `${c.item.merchant} ${c.day}`)).toEqual([
      'A 2026-02-08',
      'B 2026-02-10',
      'C 2026-02-12',
    ])
  })

  it("the amount is in the charge's currency", () => {
    expect(chargeText(item())).toBe('US$ 11.99')
    expect(chargeText(item({ currency: 'DOP', typical_cents: 250_000 }))).toBe('RD$ 2,500')
  })
})

describe('household recurring charges', () => {
  it('offers the groups in screen order', () => {
    expect(GROUP_OPTIONS.map((g) => g.key)).toEqual([
      'housing',
      'loans',
      'utilities',
      'insurance',
      'subscriptions',
      'fees',
      'other',
    ])
    expect(GROUP_OPTIONS.map((g) => g.label)).toEqual(
      GROUP_OPTIONS.map((g) => t(`recurring.group.${g.key}`)),
    )
  })

  it('on a loan the installments read as "N left"', () => {
    const loan = item({ group: 'Loans', group_key: 'loans', installments_left: 9 })
    const loanLeft = t('recurring.badge.loanLeft', { count: 9 })
    expect(badgesOf(loan, null)).toEqual([loanLeft])
    expect(badgesOf(loan, null)).toEqual(['quedan 9']) // spanish-ui
    expect(badgeTone(loanLeft)).toBe('positive')
    expect(badgesOf(item({ installments_left: 1 }), null)).toEqual([left(1)])
  })

  it("states the year's extra payments only when there were some", () => {
    expect(extrasText(item({ extras_year_cents: 0 }))).toBeNull()
    expect(extrasText(item({ currency: 'DOP', extras_year_cents: 5_000_000 }))).toBe(
      t('recurring.extras', { amount: 'RD$ 50,000' }),
    )
  })

  it("lists a provider's or a join's merchants", () => {
    expect(membersText(item())).toBeNull()
    const phone = item({
      merchant: 'provider:telfic',
      name: 'Telco Demo',
      members: ['TELFIC PAGO', 'TELFIC WB'],
    })
    expect(membersText(phone)).toBe('TELFIC PAGO, TELFIC WB')
  })

  it('joins with the other recurring items and with missing providers, by name', () => {
    const water = item({ merchant: 'AGUA FICTICIA', name: 'AGUA FICTICIA', currency: 'DOP' })
    const phone = item({ merchant: 'provider:telfic', name: 'Telco Demo' })
    const phoneUsd = item({ merchant: 'provider:telfic', name: 'Telco Demo' })
    const data = {
      ...overview([water, phone, phoneUsd], []),
      providers: [
        { key: 'provider:telfic', name: 'Telco Demo' },
        { key: 'provider:luzfic', name: 'Power Demo' },
      ],
    }
    expect(joinTargets(data, water)).toEqual([
      { key: 'provider:luzfic', name: 'Power Demo' },
      { key: 'provider:telfic', name: 'Telco Demo' },
    ])
    expect(joinTargets(data, phone).map((t) => t.key)).toEqual([
      'AGUA FICTICIA',
      'provider:luzfic',
    ])
  })

  it('sends the group and the installments of "It is recurring…" only when chosen', () => {
    expect(txRecurringBody('monthly', '', null)).toEqual({ cadence: 'monthly' })
    expect(txRecurringBody('yearly', 'housing', null)).toEqual({
      cadence: 'yearly',
      group: 'housing',
    })
    expect(txRecurringBody('monthly', 'loans', 12)).toEqual({
      cadence: 'monthly',
      group: 'loans',
      installments_left: 12,
    })
  })
})

describe('group by hand and separate', () => {
  it("the chosen group keeps the mark; empty goes back to the category's", () => {
    const marked = item({ mark: 'confirmed' })
    expect(groupBody(marked, 'housing')).toEqual({
      merchant: 'STREAMING FICTICIO',
      currency: 'USD',
      status: 'confirmed',
      group: 'housing',
    })
    expect(groupBody(marked, '').group).toBeNull()
  })

  it('does not offer to separate the merchant that names the series', () => {
    expect(separableMembers(item())).toEqual([])
    const joined = item({ merchant: 'AGUA B', members: ['AGUA B', 'AGUA C'] })
    expect(separableMembers(joined)).toEqual(['AGUA C'])
    const phone = item({ merchant: 'provider:telfic', members: ['TELFIC PAGO', 'TELFIC WB'] })
    expect(separableMembers(phone)).toEqual(['TELFIC PAGO', 'TELFIC WB'])
  })
})
