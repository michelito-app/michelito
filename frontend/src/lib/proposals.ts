// AI proposals in Review (src/michelito/web/proposal_routes.py): batches of category changes an
// AI connector sent, which the person applies (all or some) or dismisses. Their texts come from
// the AI: shown as plain text, never as markup. Pure helpers apart from the calls.
import { useQuery } from '@tanstack/react-query'
import { t } from '@/i18n'
import { request } from '@/lib/api'

export const proposalsKey = ['proposals'] as const

export type ItemStatus = 'open' | 'applied' | 'skipped' | 'failed'

export interface ProposalItem {
  id: number
  fingerprint: string
  scope: 'transaction' | 'merchant'
  reason: string
  day: string
  merchant: string
  description: string
  amount_cents: number
  currency: string
  from_category: string
  to_category_id: number
  to_category: string
  status: ItemStatus
  message: string
}

/** A loose row of an import (provisional charges or cash). */
export interface ImportRow {
  id: number
  day: string
  description: string
  amount_cents: number
  currency: string
  direction: 'out' | 'in'
  category: string // the suggested category's name ('' if none)
  duplicate_of: string // the stored transaction it seems to repeat ('' if none)
  status: ItemStatus
  message: string
}

/** One currency of a statement import: its printed totals, and whether its previous balance
 * continues the last stored statement (null: nothing to compare). */
export interface StatementSection {
  currency: string
  transactions: number
  debits_cents: number | null
  credits_cents: number | null
  closing_cents: number | null
  continues: boolean | null
}

/** The statement of a statement import, without its rows. */
export interface StatementInfo {
  period_start: string | null
  period_end: string
  currencies: string[]
  transactions: number
  document_status: string // 'parsed' once stored, 'duplicate' if it already was
  sections: StatementSection[]
}

export type ProposalKind = 'category' | 'statement' | 'provisional' | 'cash'

export interface Proposal {
  id: number
  created_at: string
  source: string
  title: string
  explanation: string
  status: 'open' | 'applying' | 'applied' | 'dismissed'
  decided_at: string | null
  kind: ProposalKind
  account_label: string
  items: ProposalItem[]
  rows: ImportRow[]
  statement: StatementInfo | null
}

export function useProposals() {
  return useQuery({ queryKey: proposalsKey, queryFn: () => request<Proposal[]>('/api/proposals') })
}

export function applyProposal(id: number, itemIds: number[]): Promise<Proposal> {
  return request<Proposal>(`/api/proposals/${id}/apply`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds }),
  })
}

export function dismissProposal(id: number): Promise<Proposal> {
  return request<Proposal>(`/api/proposals/${id}/dismiss`, { method: 'POST' })
}

export function openProposals(all: readonly Proposal[]): Proposal[] {
  return all.filter((p) => p.status === 'open')
}

/** What can be ticked: the changes or the loose rows (a statement goes whole: none). */
export function selectableIds(proposal: Proposal): number[] {
  if (proposal.kind === 'category') return proposal.items.map((i) => i.id)
  return proposal.rows.map((r) => r.id)
}

/** Ticked at first: every change, and every loose row except possible duplicates. */
export function initialTicks(proposal: Proposal): number[] {
  if (proposal.kind === 'category') return proposal.items.map((i) => i.id)
  return proposal.rows.filter((r) => !r.duplicate_of).map((r) => r.id)
}

/** The kind and account of an import (a statement, pending charges, cash) or the count of
 * category changes, under the title. */
export function kindLine(proposal: Proposal): string {
  switch (proposal.kind) {
    case 'statement':
      return t('connector.proposals.kind.statement', { account: proposal.account_label })
    case 'provisional':
      return t('connector.proposals.kind.provisional', { account: proposal.account_label })
    case 'cash':
      return t('connector.proposals.kind.cash')
    default:
      return t('connector.proposals.changes', { count: proposal.items.length })
  }
}

/** "3 aplicados · 1 omitido" for an answered proposal. */
export function outcomeLine(proposal: Proposal): string {
  if (proposal.status === 'dismissed') return t('connector.proposals.dismissed')
  if (proposal.kind === 'statement') {
    return proposal.statement?.document_status === 'duplicate'
      ? t('connector.proposals.statementAlready')
      : t('connector.proposals.statementSaved')
  }
  const all = [...proposal.items, ...proposal.rows]
  const count = (status: ItemStatus) => all.filter((i) => i.status === status).length
  return [
    t('connector.proposals.outcome.applied', { count: count('applied') }),
    count('skipped') ? t('connector.proposals.outcome.skipped', { count: count('skipped') }) : null,
    count('failed') ? t('connector.proposals.outcome.failed', { count: count('failed') }) : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** The proposal the link opened (`?proposal=12`) first, then the rest as they come. */
export function withChosenFirst(all: readonly Proposal[], chosen: number | null): Proposal[] {
  const found = all.find((p) => p.id === chosen)
  return found ? [found, ...all.filter((p) => p !== found)] : [...all]
}
