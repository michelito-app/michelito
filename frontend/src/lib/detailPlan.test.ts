import { describe, expect, it } from 'vitest'
import type { Tx } from './api'
import { detailPlan, type PlanInput } from './detailPlan'

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f',
    day: '2026-02-02',
    merchant: 'STORE',
    description: 'STORE',
    category: 'Food',
    category_id: 2,
    kind: 'expense',
    original_category: 'Food',
    account: 'visa',
    account_label: 'Visa',
    amount_cents: 300_000,
    currency: 'DOP',
    amount_dop_cents: 300_000,
    one_off: false,
    corrected: false,
    merchant_year_count: 1,
    suggested_one_off: false,
    one_off_reasons: [],
    one_off_dismissed: false,
    note: '',
    link: '',
    gross_cents: null,
    pending_cents: 0,
    shared: null,
    reimbursement_of: null,
    suggested_group: null,
    exchange: null,
    suggested_exchange_with: null,
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
    link_id: null,
    can_share: false,
    can_reimburse: false,
    can_exchange: false,
    ...overrides,
  }
}

const NONE = { linked: null, available: false }
const NO_RESERVE = { linked: null, canLink: false, reason: '' }

function plan(overrides: Partial<Tx>, rest: Partial<Omit<PlanInput, 'tx'>> = {}) {
  return detailPlan({ tx: tx(overrides), reserve: NO_RESERVE, recurring: NONE, ...rest })
}

describe('detailPlan', () => {
  it('a plain expense: one-off and history only', () => {
    expect(plan({})).toEqual({ links: [], actions: ['oneOff', 'history'], reserveNote: null })
  })

  it('an income offers no one-off; a reimbursable credit offers the reimbursement', () => {
    const { actions } = plan({ kind: 'income', amount_cents: -5_000, can_reimburse: true })
    expect(actions).toEqual(['reimbursement', 'history'])
  })

  it('offers only what the server allows', () => {
    const { actions } = plan(
      { can_invest: true, can_store: true, can_exchange: true },
      {
        reserve: { linked: null, canLink: true, reason: '' },
        recurring: { linked: null, available: true },
      },
    )
    expect(actions).toEqual([
      'oneOff',
      'investment',
      'cashBox',
      'reserve',
      'recurring',
      'exchange',
      'history',
    ])
  })

  it('an existing link goes on top and leaves the list', () => {
    const result = plan(
      { link: 'exchange', can_exchange: false },
      { reserve: { linked: 'Travel', canLink: false, reason: '' } },
    )
    expect(result.links.map((line) => line.kind)).toEqual(['exchange', 'reserve'])
    expect(result.links[1].text).toContain('Travel')
    expect(result.actions).not.toContain('exchange')
    expect(result.actions).not.toContain('reserve')
  })

  it('a cash box movement is a link, not an action', () => {
    const result = plan({ cash_box_role: 'stored', can_store: true })
    expect(result.links.map((line) => line.kind)).toEqual(['cashBox'])
    expect(result.actions).not.toContain('cashBox')
  })

  it('a suggestion is not a link', () => {
    const result = plan({ can_share: true })
    expect(result.links).toEqual([])
  })

  it('a reserve that cannot be linked is not an action: its reason is a note', () => {
    const result = plan({}, { reserve: { linked: null, canLink: false, reason: 'Too old' } })
    expect(result.actions).not.toContain('reserve')
    expect(result.reserveNote).toBe('Too old')
    expect(plan({}).reserveNote).toBeNull()
    // Already covered: neither action nor note.
    const covered = plan({}, { reserve: { linked: 'Travel', canLink: false, reason: 'Linked' } })
    expect(covered.reserveNote).toBeNull()
  })
})
