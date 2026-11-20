import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import {
  amountCents,
  balanceTone,
  byMonth,
  defaultPayer,
  differenceText,
  displayName,
  draftOf,
  draftShortfall,
  draftValid,
  effectText,
  entryLine,
  equalDraft,
  equalShares,
  groupBalanceText,
  groupSentence,
  groupSides,
  paymentWarning,
  initials,
  paymentDraft,
  paymentLine,
  peopleOptions,
  personBalanceText,
  shortfall,
  shortfallText,
  splitFields,
  splitSettled,
  splitSummary,
  totalsLines,
} from './ledger'
import type { BankName, Contact, Person } from './sharedApi'

const ME = 1
const ANA = 2
const LUIS = 3

describe('equalShares (the server cent rule)', () => {
  it('divides in cents; the leftover goes to the payer', () => {
    expect(equalShares(1000, [ME, ANA, LUIS], ANA)).toEqual([
      { contact_id: ME, cents: 333 },
      { contact_id: ANA, cents: 334 },
      { contact_id: LUIS, cents: 333 },
    ])
  })

  it('to the first person when the payer is not among them, without repeats', () => {
    expect(equalShares(1001, [ANA, LUIS, ANA], ME)).toEqual([
      { contact_id: ANA, cents: 501 },
      { contact_id: LUIS, cents: 500 },
    ])
    expect(equalShares(500, [], ME)).toEqual([])
  })

  it('always adds up to the total', () => {
    for (const total of [1, 2, 99, 100, 12_345, 1_000_001]) {
      const sum = equalShares(total, [ME, ANA, LUIS, 4, 5, 6, 7], LUIS).reduce((a, s) => a + s.cents, 0)
      expect(sum).toBe(total)
    }
  })
})

describe('exact split and shortfall', () => {
  const exact = { mode: 'exact' as const, people: [ME, ANA], shares: { [ME]: '300', [ANA]: '' } }

  it('says what is missing or over, live', () => {
    expect(shortfall(100_000, [30_000])).toBe(70_000)
    expect(draftShortfall(exact, 100_000)).toBe(70_000)
    expect(shortfallText(20_000, 'DOP')).toBe(t('shared.split.missing', { amount: 'RD$ 200' }))
    expect(shortfallText(-5_000, 'DOP')).toBe(t('shared.split.over', { amount: 'RD$ 50' }))
    expect(shortfallText(0, 'DOP')).toBe(t('shared.split.addsUp'))
    expect(draftShortfall({ ...exact, shares: { [ME]: 'x' } }, 100_000)).toBeNull()
  })

  it('is valid only when it adds up (equal: someone checked)', () => {
    expect(draftValid(exact, 100_000)).toBe(false)
    expect(draftValid({ ...exact, shares: { [ME]: '300', [ANA]: '700' } }, 100_000)).toBe(true)
    expect(draftValid(equalDraft([ME]), 100_000)).toBe(true)
    expect(draftValid(equalDraft([]), 100_000)).toBe(false)
  })

  it('builds the request without zero shares, and drafts a saved split back', () => {
    expect(splitFields(equalDraft([ME, ANA]))).toEqual({ split: 'equal', people: [ME, ANA] })
    expect(splitFields({ ...exact, shares: { [ME]: '1,000.50', [ANA]: '0' } })).toEqual({
      split: 'exact',
      shares: [{ contact_id: ME, cents: 100_050 }],
    })
    const saved = {
      split: 'exact' as const,
      splits: [
        { contact_id: ME, name: 'me', is_me: true, cents: 30_000 },
        { contact_id: ANA, name: 'Ana', is_me: false, cents: 70_000 },
      ],
    }
    expect(draftOf(saved)).toEqual({ mode: 'exact', people: [ME, ANA], shares: { [ME]: '300.00', [ANA]: '700.00' } })
    expect(draftOf({ ...saved, split: 'equal' })).toEqual(equalDraft([ME, ANA]))
  })

  it('reads amounts, with or without a zero', () => {
    expect(amountCents('1,250.5')).toBe(125_050)
    expect(amountCents('0')).toBeNull()
    expect(amountCents('0', true)).toBe(0)
    expect(amountCents('1.234')).toBeNull()
  })
})

describe('texts', () => {
  const members = [
    { id: ME, name: 'me', is_me: true },
    { id: ANA, name: 'Ana', is_me: false },
  ]

  it('the split summary line', () => {
    expect(splitSummary(equalDraft([ME, ANA, LUIS, 4]), 500_000, 'DOP', members)).toBe(
      t('shared.add.splitEqual', { count: 4, amount: 'RD$ 1,250' }),
    )
    expect(splitSummary(equalDraft([ANA]), 500_000, 'DOP', members)).toBe(
      t('shared.add.splitEqualOne', { name: 'Ana' }),
    )
    expect(splitSummary({ mode: 'exact', people: [ME], shares: {} }, 1, 'DOP', members)).toBe(
      t('shared.add.splitExact'),
    )
  })

  it('initials and the user', () => {
    expect(initials('Ana Ficticia Pérez')).toBe('AF') // spanish-data
    expect(initials('luis')).toBe('L')
    expect(displayName('me', true)).toBe(t('shared.you'))
    expect(displayName('Ana', false)).toBe('Ana')
  })

  it('balances: tone and text, both directions and currencies', () => {
    expect(balanceTone([])).toBe('settled')
    expect(balanceTone([{ currency: 'DOP', cents: -300 }])).toBe('owe')
    expect(personBalanceText([{ currency: 'DOP', cents: 125_000 }])).toBe(
      t('shared.balance.owesYou', { amount: 'RD$ 1,250' }),
    )
    expect(
      personBalanceText([
        { currency: 'DOP', cents: -30_000 },
        { currency: 'USD', cents: 1_000 },
      ]),
    ).toBe(
      `${t('shared.balance.youOwe', { amount: 'RD$ 300' })} · ${t('shared.balance.owesYou', { amount: 'US$ 10.00' })}`,
    )
    expect(groupBalanceText([])).toBe(t('shared.balance.settled'))
    expect(groupSentence([{ currency: 'DOP', cents: 210_000 }])).toBe(
      t('shared.group.sentence.owed', { amount: 'RD$ 2,100' }),
    )
    expect(groupSentence([])).toBe(t('shared.group.sentence.settled'))
  })

  it('a group shows both sides when someone owes the user and the user owes someone else', () => {
    const parts = groupSides([{ currency: 'DOP', cents: 10_000 }], [{ currency: 'DOP', cents: 10_000 }])
    expect(parts).toEqual([
      { currency: 'DOP', cents: 10_000 },
      { currency: 'DOP', cents: -10_000 },
    ])
    expect(groupSentence(parts)).toBe(
      `${t('shared.group.sentence.owed', { amount: 'RD$ 100' })} · ${t('shared.group.sentence.owe', { amount: 'RD$ 100' })}`,
    )
    expect(groupSides([], [])).toEqual([])
  })

  it('the home totals: RD$ first, one line per extra currency', () => {
    expect(
      totalsLines([
        { currency: 'USD', owed_to_me_cents: 1_000, i_owe_cents: 0 },
        { currency: 'DOP', owed_to_me_cents: 400_000, i_owe_cents: 50_000 },
        { currency: 'EUR', owed_to_me_cents: 0, i_owe_cents: 0 },
      ]),
    ).toEqual([
      t('shared.totals.line', { owed: 'RD$ 4,000', owe: 'RD$ 500' }),
      t('shared.totals.line', { owed: 'US$ 10.00', owe: 'US$ 0.00' }),
    ])
  })

  it('timeline rows and the effect on the user', () => {
    const entry = { description: 'Cena', paid_by_name: 'Ana', paid_by_me: false, amount_cents: 500_000, currency: 'DOP' }
    expect(entryLine(entry)).toBe(
      t('shared.entry.line', { description: 'Cena', payer: 'Ana', amount: 'RD$ 5,000' }),
    )
    expect(effectText({ kind: 'owe', cents: 125_000 }, 'DOP')).toBe(
      t('shared.entry.owe', { amount: 'RD$ 1,250' }),
    )
    expect(effectText({ kind: 'lent', cents: 375_000 }, 'DOP')).toBe(
      t('shared.entry.lent', { amount: 'RD$ 3,750' }),
    )
    const payment = {
      from_contact: LUIS,
      from_name: 'Luis',
      from_me: false,
      to_name: 'me',
      to_me: true,
      amount_cents: 100_000,
      currency: 'DOP',
    }
    expect(paymentLine(payment)).toBe(
      t('shared.payment.line', { from: 'Luis', to: t('shared.you'), amount: 'RD$ 1,000' }),
    )
    expect(paymentLine({ ...payment, from_contact: null })).toContain(t('shared.payment.unknown'))
  })

  it('groups the timeline by month, keeping the order', () => {
    const items = [{ day: '2026-02-09' }, { day: '2026-02-01' }, { day: '2026-01-20' }]
    expect(byMonth(items).map((b) => [b.month, b.items.length])).toEqual([
      ['2026-02', 2],
      ['2026-01', 1],
    ])
  })

  it('the difference of a payment', () => {
    const base = { amount_cents: 120_000, currency: 'DOP' }
    expect(differenceText({ ...base, sent_cents: null, difference_cents: null })).toBeNull()
    expect(differenceText({ ...base, sent_cents: 125_000, difference_cents: 5_000 })).toBe(
      t('shared.detail.difference', { sent: 'RD$ 1,250', received: 'RD$ 1,200', difference: 'RD$ 50' }),
    )
  })
})

describe('payments and people', () => {
  it('a payment starts from the balance: who pays and the whole amount', () => {
    expect(paymentDraft([{ currency: 'DOP', cents: 125_000 }])).toEqual({
      received: true,
      cents: 125_000,
      currency: 'DOP',
    })
    expect(paymentDraft([{ currency: 'USD', cents: -2_000 }])).toEqual({
      received: false,
      cents: 2_000,
      currency: 'USD',
    })
    expect(paymentDraft([])).toEqual({ received: true, cents: 0, currency: 'DOP' })
  })

  it('«Paid by»: the most recent payer in the group, else the first', () => {
    expect(defaultPayer([ANA, LUIS], [9, LUIS, ANA])).toBe(LUIS)
    expect(defaultPayer([ANA, LUIS], [])).toBe(ANA)
    expect(defaultPayer([], [ANA])).toBeNull()
  })

  it('settled people go apart', () => {
    const person = (id: number, cents: number): Person => ({
      id,
      name: String(id),
      aliases: [],
      balance: cents ? [{ currency: 'DOP', cents }] : [],
      group_count: 1,
      groups: [],
    })
    const { open, settled } = splitSettled([person(1, 100), person(2, 0), person(3, -5)])
    expect(open.map((p) => p.id)).toEqual([1, 3])
    expect(settled.map((p) => p.id)).toEqual([2])
  })

  it('the picker: contacts (name or alias), names seen in the bank, then «Create»', () => {
    const contacts: Contact[] = [
      { id: ME, name: 'me', is_me: true, aliases: [] },
      { id: ANA, name: 'Ana', is_me: false, aliases: ['ANA FICTICIA'] },
      { id: LUIS, name: 'Luis', is_me: false, aliases: ['LUIS ANAYA'] },
    ]
    const banks: BankName[] = [{ name: 'Anabel Ficticia', raw: 'ANABEL FICTICIA', count: 1, last_day: '2026-02-01' }]
    const kinds = (query: string, taken = new Set<number>()) =>
      peopleOptions(query, contacts, banks, taken).map((o) =>
        o.kind === 'contact' ? `c:${o.contact.name}` : o.kind === 'bank' ? `b:${o.bank.name}` : `n:${o.name}`,
      )
    expect(kinds('an')).toEqual(['c:Ana', 'c:Luis', 'b:Anabel Ficticia', 'n:an'])
    expect(kinds('ana')).toEqual(['c:Ana', 'c:Luis', 'b:Anabel Ficticia'])
    // An exact existing name is not offered to create again; chosen contacts are left out.
    expect(kinds('Ana', new Set([ANA]))).toEqual(['c:Luis', 'b:Anabel Ficticia'])
    expect(kinds('  ')).toEqual([])
    expect(kinds('me')).toEqual(['n:me'])
  })
})

describe('paymentWarning', () => {
  const owes = [{ currency: 'DOP', cents: 125_000 }]
  it('says nothing when the payment fits the balance', () => {
    expect(paymentWarning(owes, true, 125_000, 'DOP', 'Ana')).toBeNull()
    expect(paymentWarning(owes, true, 50_000, 'DOP', 'Ana')).toBeNull()
    expect(paymentWarning(owes, true, null, 'DOP', 'Ana')).toBeNull()
  })
  it('warns when it goes beyond the balance or against it', () => {
    expect(paymentWarning(owes, true, 150_000, 'DOP', 'Ana')).toBe(
      t('shared.pay.warnOver', { name: 'Ana', amount: 'RD$ 250' }),
    )
    expect(paymentWarning(owes, false, 10_000, 'DOP', 'Ana')).toBe(
      t('shared.pay.warnAgainstYou', { name: 'Ana', amount: 'RD$ 100' }),
    )
    expect(paymentWarning([], true, 1_000, 'USD', 'Ana')).toBe(
      t('shared.pay.warnAgainst', { name: 'Ana', amount: 'US$ 10.00' }),
    )
  })
})
