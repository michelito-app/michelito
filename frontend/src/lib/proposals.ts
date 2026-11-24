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

export interface Proposal {
  id: number
  created_at: string
  source: string
  title: string
  explanation: string
  status: 'open' | 'applied' | 'dismissed'
  decided_at: string | null
  items: ProposalItem[]
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

/** "3 aplicados · 1 omitido" for an answered proposal. */
export function outcomeLine(proposal: Proposal): string {
  if (proposal.status === 'dismissed') return t('connector.proposals.dismissed')
  const count = (status: ItemStatus) => proposal.items.filter((i) => i.status === status).length
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
