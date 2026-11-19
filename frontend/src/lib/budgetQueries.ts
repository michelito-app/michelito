// Budget and reserve queries. Every write refetches the budget, the reserves, the Summary card,
// "To review" and the transactions (and with them, the log).
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Selection, selectionParam, withAccounts } from './accountFilter'
import { request } from './api'
import type {
  Budget,
  BudgetOverview,
  MembersResult,
  ReserveBody,
  Reserves,
  TxReserve,
} from './budget'
import { queryKeys } from './queries'

function scope(selection: Selection): string {
  return selectionParam(selection) ?? 'all'
}

export const budgetKeys = {
  all: ['budget'] as const,
  month: (month: string, selection: Selection) =>
    ['budget', 'month', month, scope(selection)] as const,
  overview: (month: string, selection: Selection) =>
    ['budget', 'overview', month, scope(selection)] as const,
  reserves: (selection: Selection) => ['budget', 'reserves', scope(selection)] as const,
  tx: (fingerprint: string) => ['budget', 'tx', fingerprint] as const,
  options: ['budget', 'options'] as const,
}

function useInvalidate() {
  const client = useQueryClient()
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: budgetKeys.all }),
      client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
      client.invalidateQueries({ queryKey: queryKeys.transactions }),
    ])
}

/** Caps and spending of the month per category (selected accounts). */
export function useBudget(month: string | null, selection: Selection) {
  return useQuery({
    queryKey: budgetKeys.month(month ?? '', selection),
    queryFn: () =>
      request<Budget>(
        withAccounts(`/api/budget?month=${encodeURIComponent(month ?? '')}`, selection),
      ),
    enabled: month !== null,
    placeholderData: keepPreviousData,
  })
}

/** The Summary card and the "after setting aside" line of "Left over". */
export function useBudgetOverview(month: string, selection: Selection) {
  return useQuery({
    queryKey: budgetKeys.overview(month, selection),
    queryFn: () =>
      request<BudgetOverview>(
        withAccounts(`/api/budget/overview?month=${encodeURIComponent(month)}`, selection),
      ),
    placeholderData: keepPreviousData,
  })
}

export function useReserves(selection: Selection, enabled = true) {
  return useQuery({
    queryKey: budgetKeys.reserves(selection),
    queryFn: () => request<Reserves>(withAccounts('/api/reserves', selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** Only the id and name of each reserve (the multiple-selection picker). */
export function useReserveOptions() {
  return useQuery({
    queryKey: budgetKeys.options,
    queryFn: () => request<{ id: number; name: string }[]>('/api/reserves/options'),
  })
}

export function useTxReserve(fingerprint: string, enabled: boolean) {
  return useQuery({
    queryKey: budgetKeys.tx(fingerprint),
    queryFn: () =>
      request<TxReserve>(`/api/transactions/${encodeURIComponent(fingerprint)}/reserve`),
    enabled,
  })
}

interface EntryResult {
  entry_id: number | null
}

export function useActivateBudget() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: () => request<EntryResult>('/api/budget/activate', { method: 'POST' }),
    onSuccess: invalidate,
  })
}

/** The manual cap (null: "No budget"). */
export function useSetCap() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ categoryId, cents }: { categoryId: number; cents: number | null }) =>
      request<EntryResult>(`/api/budget/caps/${categoryId}`, {
        method: 'PUT',
        body: JSON.stringify({ cap_cents: cents }),
      }),
    onSuccess: invalidate,
  })
}

/** Accept or ignore the "the usual changed" warning. */
export function useResolveWarning() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ categoryId, accept }: { categoryId: number; accept: boolean }) =>
      request<EntryResult>(`/api/budget/caps/${categoryId}/usual`, {
        method: 'POST',
        body: JSON.stringify({ accept }),
      }),
    onSuccess: invalidate,
  })
}

export type ReserveChange =
  | { action: 'create'; body: ReserveBody }
  | { action: 'update'; id: number; body: Partial<ReserveBody> & { once?: boolean } }
  | { action: 'delete'; id: number }
  | { action: 'dismiss'; key: string; name: string }
  | { action: 'unlink'; id: number; fingerprint: string }

/** Create, edit or delete a reserve, dismiss a suggestion or remove an expense. */
export function useChangeReserve() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (change: ReserveChange): Promise<unknown> => {
      switch (change.action) {
        case 'create':
          return request('/api/reserves', { method: 'POST', body: JSON.stringify(change.body) })
        case 'update':
          return request(`/api/reserves/${change.id}`, {
            method: 'PATCH',
            body: JSON.stringify(change.body),
          })
        case 'delete':
          return request(`/api/reserves/${change.id}`, { method: 'DELETE' })
        case 'dismiss':
          return request('/api/reserve-suggestions/dismiss', {
            method: 'POST',
            body: JSON.stringify({ key: change.key, name: change.name }),
          })
        case 'unlink':
          return request(
            `/api/reserves/${change.id}/members/${encodeURIComponent(change.fingerprint)}`,
            { method: 'DELETE' },
          )
      }
    },
    onSuccess: invalidate,
  })
}

/** Links one or more expenses to a reserve (from the detail, "To review" or the selection). */
export function useLinkToReserve() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, fingerprints }: { id: number; fingerprints: string[] }) =>
      request<MembersResult>(`/api/reserves/${id}/members`, {
        method: 'POST',
        body: JSON.stringify({ fingerprints }),
      }),
    onSuccess: invalidate,
  })
}
