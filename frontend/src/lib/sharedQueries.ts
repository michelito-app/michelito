// Shared (the ledger) queries and writes. The keys live under `transactions`: every change of a
// transaction or a link refetches them, and a ledger write refetches everything (a group
// movement counts in Transactions, Summary, Budget, Pending and To review).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { t } from '@/i18n'
import { type Candidate, type LinkedTx, request, type ReviewItem } from './api'
import { type LogPage, logPath } from './log'
import { queryKeys } from './queries'
import type {
  Contacts,
  CoverBody,
  CoverPlan,
  EntryBody,
  Group,
  MemberUsage,
  NewPerson,
  PaymentBody,
  PaymentPatch,
  Person,
  Proposal,
  ShareBody,
  SharedHome,
} from './sharedApi'

export const sharedKeys = {
  all: [...queryKeys.transactions, 'shared'] as const,
  home: [...queryKeys.transactions, 'shared', 'home'] as const,
  contacts: [...queryKeys.transactions, 'shared', 'contacts'] as const,
  person: (id: number) => [...queryKeys.transactions, 'shared', 'person', id] as const,
  group: (id: number) => [...queryKeys.transactions, 'shared', 'group', id] as const,
  expenseCandidates: [...queryKeys.transactions, 'shared', 'expense-candidates'] as const,
  paymentCandidates: (query: PaymentQuery) =>
    [...queryKeys.transactions, 'shared', 'payment-candidates', paymentQueryString(query)] as const,
  proposal: (query: ProposalQuery) =>
    [...queryKeys.transactions, 'shared', 'proposal', query.group_id, proposalQueryString(query)] as const,
}

/** What "Also pays for…" asks the server to propose (`ledger.propose_allocations`). */
export interface ProposalQuery {
  group_id: number
  from_contact: number
  amount_cents: number
  currency: string
  day: string
  covers: readonly number[] // in the order they were checked
  payment_id?: number | null // an existing payment: at its own position
}

function proposalQueryString(query: ProposalQuery): string {
  const params = new URLSearchParams({
    from_contact: String(query.from_contact),
    amount_cents: String(query.amount_cents),
    currency: query.currency,
    day: query.day,
    covers: query.covers.join(','),
  })
  if (query.payment_id != null) params.set('payment_id', String(query.payment_id))
  return params.toString()
}

/** "Yes" to the group's suggestion: each payment proposed in order and the balances after. */
export function useCoverPlan(groupId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...sharedKeys.group(groupId), 'cover-plan'] as const,
    queryFn: () => request<CoverPlan>(groupPath(groupId, '/cover-proposal')),
    enabled,
  })
}

/** The proposed allocations (payer first, then the others in order, converted); none while
 * nobody else is checked. */
export function useProposal(query: ProposalQuery | null) {
  return useQuery({
    queryKey: sharedKeys.proposal(
      query ?? { group_id: 0, from_contact: 0, amount_cents: 0, currency: '', day: '', covers: [] },
    ),
    queryFn: () =>
      request<Proposal>(
        `/api/shared/groups/${query!.group_id}/allocation-proposal?${proposalQueryString(query!)}`,
      ),
    enabled: query !== null,
  })
}

export function useSharedHome() {
  return useQuery({ queryKey: sharedKeys.home, queryFn: () => request<SharedHome>('/api/shared') })
}

export function useContacts(enabled = true) {
  return useQuery({
    queryKey: sharedKeys.contacts,
    queryFn: () => request<Contacts>('/api/shared/contacts'),
    enabled,
  })
}

export function usePerson(id: number) {
  return useQuery({
    queryKey: sharedKeys.person(id),
    queryFn: () => request<Person>(`/api/shared/people/${id}`),
  })
}

export function useGroup(id: number | null) {
  return useQuery({
    queryKey: sharedKeys.group(id ?? 0),
    queryFn: () => request<Group>(`/api/shared/groups/${id}`),
    enabled: id !== null,
  })
}

/** "I paid it": recent expenses not in a group, likely ones first (`primary`). */
export function useExpenseCandidates(enabled: boolean) {
  return useQuery({
    queryKey: sharedKeys.expenseCandidates,
    queryFn: () => request<Candidate[]>('/api/shared/expense-candidates'),
    enabled,
  })
}

/** The payment whose bank transaction is looked for ("Is it in your bank yet?"). */
export interface PaymentQuery {
  contact_id: number
  received: boolean
  amount_cents: number
  day: string
  currency: string
}

function paymentQueryString(query: PaymentQuery): string {
  return new URLSearchParams({
    contact_id: String(query.contact_id),
    received: String(query.received),
    amount_cents: String(query.amount_cents),
    day: query.day,
    currency: query.currency,
  }).toString()
}

export function usePaymentCandidates(query: PaymentQuery | null) {
  return useQuery({
    queryKey: sharedKeys.paymentCandidates(
      query ?? { contact_id: 0, received: true, amount_cents: 0, day: '', currency: '' },
    ),
    queryFn: () =>
      request<LinkedTx[]>(`/api/shared/payment-candidates?${paymentQueryString(query!)}`),
    enabled: query !== null,
  })
}

const post = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) })
const patch = (body: unknown) => ({ method: 'PATCH', body: JSON.stringify(body) })
const put = (body: unknown) => ({ method: 'PUT', body: JSON.stringify(body) })
const DELETE = { method: 'DELETE' }
const groupPath = (id: number, rest = '') => `/api/shared/groups/${id}${rest}`

/** Every ledger write (each returns what the API returns: usually the fresh group). */
export const ledger = {
  createGroup: (name: string, people: NewPerson[], categoryId: number | null = null) =>
    request<Group>('/api/shared/groups', post({ name, people, category_id: categoryId })),
  patchGroup: (id: number, body: { name?: string; archived?: boolean; category_id?: number | null }) =>
    request<Group>(groupPath(id), patch(body)),
  addMember: (id: number, person: NewPerson) =>
    request<Group>(groupPath(id, '/members'), post(person)),
  removeMember: (id: number, contactId: number, resplit = false) =>
    request<Group>(groupPath(id, `/members/${contactId}${resplit ? '?resplit=true' : ''}`), DELETE),
  memberUsage: (id: number, contactId: number) =>
    request<MemberUsage>(groupPath(id, `/members/${contactId}/usage`)),
  writeOff: (id: number, contactId: number | null, writtenOff: boolean) =>
    request<Group>(
      groupPath(id, '/write-off'),
      post({ contact_id: contactId, written_off: writtenOff }),
    ),
  addEntry: (id: number, body: EntryBody) => request<Group>(groupPath(id, '/entries'), post(body)),
  putEntry: (entryId: number, body: EntryBody) =>
    request<Group>(`/api/shared/entries/${entryId}`, put(body)),
  deleteEntry: (entryId: number) => request<Group>(`/api/shared/entries/${entryId}`, DELETE),
  addPayment: (id: number, body: PaymentBody) =>
    request<Group>(groupPath(id, '/payments'), post(body)),
  patchPayment: (paymentId: number, body: PaymentPatch) =>
    request<Group>(`/api/shared/payments/${paymentId}`, patch(body)),
  deletePayment: (paymentId: number) => request<Group>(`/api/shared/payments/${paymentId}`, DELETE),
  setAllocations: (paymentId: number, allocations: ShareBody[]) =>
    request<Group>(`/api/shared/payments/${paymentId}/allocations`, put({ allocations })),
  /** "No" to a suggestion: every payment of it, as one change. */
  dismissCovers: (id: number, paymentIds: readonly number[], dismissed = true) =>
    request<Group>(groupPath(id, '/cover-dismissed'), put({ payment_ids: paymentIds, dismissed })),
  /** "Yes" confirmed: every payment's allocations, as one change. */
  applyCover: (id: number, body: CoverBody) => request<Group>(groupPath(id, '/cover'), put(body)),
  setLeftover: (id: number, contactId: number, settled: boolean) =>
    request<Group>(groupPath(id, '/exchange-leftover'), post({ contact_id: contactId, settled })),
  createContact: (name: string, alias?: string) =>
    request<{ id: number }>('/api/shared/contacts', post({ name, alias })),
  renameContact: (id: number, name: string) =>
    request<Contacts>(`/api/shared/contacts/${id}`, patch({ name })),
  addAlias: (id: number, alias: string) =>
    request<Contacts>(`/api/shared/contacts/${id}/aliases`, post({ alias })),
  removeAlias: (id: number, alias: string) =>
    request<Contacts>(`/api/shared/contacts/${id}/aliases/${encodeURIComponent(alias)}`, DELETE),
  merge: (id: number, into: number) =>
    request<Contacts>(`/api/shared/contacts/${id}/merge`, post({ into })),
  reviewPeopleDone: () => request<void>('/api/shared/review-people/done', { method: 'POST' }),
}

/** The newest log entry of a kind (the one a write just made): its id, for "Undo". */
export async function lastLogId(kind: string): Promise<number | null> {
  const page = await request<LogPage>(logPath({ kind, author: null, q: '' }, 0, 1))
  return page.items[0]?.id ?? null
}

/** "To review"'s "Did Ana pay you?" answered yes: records the payment with that credit (or links
 * the unlinked payment it reconciles). Never called without the user's tap. */
export async function confirmPossiblePayment(item: ReviewItem): Promise<Group> {
  if (item.payment_id != null) {
    return ledger.patchPayment(item.payment_id, { fingerprint: item.fingerprint })
  }
  const contacts = await request<Contacts>('/api/shared/contacts')
  const me = contacts.contacts.find((c) => c.is_me)
  if (!me || item.group_id == null) throw new Error(t('shared.unknownGroup'))
  return ledger.addPayment(item.group_id, {
    from_contact: item.contact_id ?? null,
    to_contact: me.id,
    amount_cents: item.amount_cents,
    currency: item.currency,
    day: item.day,
    fingerprint: item.fingerprint,
  })
}

/** Runs a ledger write; on success the group it returns is stored and everything is refetched
 * (balances show up in Transactions, Summary, Pending and To review). */
export function useLedgerWrite<T = Group>() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (write: () => Promise<T>) => write(),
    onSuccess: (result) => {
      if (isGroup(result)) client.setQueryData(sharedKeys.group(result.id), result)
      return client.invalidateQueries()
    },
  })
}

function isGroup(value: unknown): value is Group {
  return (
    typeof value === 'object' &&
    value !== null &&
    'timeline' in value &&
    'members' in value &&
    typeof (value as { id?: unknown }).id === 'number'
  )
}
