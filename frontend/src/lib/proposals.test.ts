import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import {
  type ImportRow,
  type Proposal,
  type ProposalItem,
  initialTicks,
  kindLine,
  openProposals,
  outcomeLine,
  selectableIds,
  withChosenFirst,
} from './proposals'

function item(id: number, status: ProposalItem['status']): ProposalItem {
  return {
    id,
    fingerprint: `f${id}`,
    scope: 'transaction',
    reason: '',
    day: '2026-01-15',
    merchant: 'COLMADO INVENTADO',
    description: 'COLMADO INVENTADO',
    amount_cents: 120050,
    currency: 'DOP',
    from_category: 'Supermercado',
    to_category_id: 3,
    to_category: 'Restaurantes',
    status,
    message: '',
  }
}

function proposal(id: number, status: Proposal['status'], items: ProposalItem[] = []): Proposal {
  return {
    id,
    created_at: '',
    source: 'Claude',
    title: `P${id}`,
    explanation: '',
    status,
    decided_at: null,
    kind: 'category',
    account_label: '',
    items,
    rows: [],
    statement: null,
  }
}

describe('proposals', () => {
  it('keeps only the open ones', () => {
    expect(openProposals([proposal(1, 'open'), proposal(2, 'applied')]).map((p) => p.id)).toEqual([1])
  })

  it('puts the one the link named first', () => {
    const all = [proposal(1, 'open'), proposal(2, 'open'), proposal(3, 'open')]
    expect(withChosenFirst(all, 2).map((p) => p.id)).toEqual([2, 1, 3])
    expect(withChosenFirst(all, 9).map((p) => p.id)).toEqual([1, 2, 3])
    expect(withChosenFirst(all, null).map((p) => p.id)).toEqual([1, 2, 3])
  })

  it('says what happened to each change', () => {
    const done = proposal(1, 'applied', [item(1, 'applied'), item(2, 'applied'), item(3, 'skipped')])
    expect(outcomeLine(done)).toBe(
      `${t('connector.proposals.outcome.applied', { count: 2 })} · ${t('connector.proposals.outcome.skipped', { count: 1 })}`,
    )
    expect(outcomeLine(proposal(2, 'dismissed'))).toBe(t('connector.proposals.dismissed'))
  })

  it('leaves possible duplicates unticked in an import', () => {
    const row = (id: number, duplicate: string): ImportRow => ({
      id,
      day: '2026-01-15',
      description: 'MADE UP',
      amount_cents: 100,
      currency: 'DOP',
      direction: 'out',
      category: '',
      duplicate_of: duplicate,
      status: 'open',
      message: '',
    })
    const found: Proposal = { ...proposal(1, 'open'), kind: 'cash', rows: [row(1, ''), row(2, 'f9')] }
    expect(initialTicks(found)).toEqual([1])
    expect(selectableIds(found)).toEqual([1, 2])
    expect(kindLine(found)).toBe(t('connector.proposals.kind.cash'))
  })

  it('names the account of a statement import', () => {
    const found: Proposal = { ...proposal(1, 'open'), kind: 'statement', account_label: 'Ahorros ••1111' }
    const done: Proposal = {
      ...found,
      status: 'applied',
      statement: { period_start: null, period_end: '2026-03-31', currencies: ['DOP'], transactions: 1, document_status: 'duplicate', sections: [] },
    }
    expect(outcomeLine(done)).toBe(t('connector.proposals.statementAlready'))
    expect(kindLine(found)).toBe(t('connector.proposals.kind.statement', { account: 'Ahorros ••1111' }))
    expect(initialTicks(found)).toEqual([])
  })
})
