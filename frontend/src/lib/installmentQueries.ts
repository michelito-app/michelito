// Installment plans: their cards, the "It is an installment…" draft and the writes. A write
// changes the rows' tags, Recurring's forecast, To review and (a member's plan) the shared
// groups: all of them are invalidated.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type InstallmentBody,
  type InstallmentDraft,
  type InstallmentPlan,
  request,
} from './api'
import { queryKeys } from './queries'

export const installmentKeys = {
  all: ['installments'] as const,
  // Under the transactions' key: it changes with them.
  draft: (fingerprint: string) =>
    [...queryKeys.transactions, 'installment-draft', fingerprint] as const,
}

function planPath(id: number): string {
  return `/api/installments/${id}`
}

function linkPath(id: number, fingerprint: string): string {
  return `${planPath(id)}/transactions/${encodeURIComponent(fingerprint)}`
}

export function useInstallments(enabled = true) {
  return useQuery({
    enabled,
    queryKey: installmentKeys.all,
    queryFn: () => request<InstallmentPlan[]>('/api/installments'),
  })
}

export function useInstallmentDraft(fingerprint: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: installmentKeys.draft(fingerprint),
    queryFn: () =>
      request<InstallmentDraft>(
        `/api/transactions/${encodeURIComponent(fingerprint)}/installment-draft`,
      ),
  })
}

function useInvalidatePlans() {
  const client = useQueryClient()
  return () =>
    Promise.all(
      [
        installmentKeys.all,
        queryKeys.transactions, // also the shared groups (their keys live under it)
        queryKeys.recurringAll,
        queryKeys.reviewAll,
        queryKeys.summaries,
        queryKeys.oneOffsAll,
        queryKeys.pendingAll,
      ].map((queryKey) => client.invalidateQueries({ queryKey })),
    )
}

/** "It is an installment…": the plan, from a charge (the earlier matching ones are linked too). */
export function useCreateInstallment() {
  const invalidate = useInvalidatePlans()
  return useMutation({
    mutationFn: (body: InstallmentBody) =>
      request<InstallmentPlan>('/api/installments', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
  })
}

/** "Delete plan": the plan and the group expenses it recorded; the transactions stay. */
export function useDeleteInstallment() {
  const invalidate = useInvalidatePlans()
  return useMutation({
    mutationFn: (id: number) => request<void>(planPath(id), { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export interface LinkChange {
  planId: number
  fingerprint: string
  /** "It is installment n"; null: "it is not part of the plan" (refused for good). */
  number: number | null
}

/** An off-script charge: "it is installment n" or "it is not part of the plan". */
export function useChangeInstallmentLink() {
  const invalidate = useInvalidatePlans()
  return useMutation({
    mutationFn: ({ planId, fingerprint, number }: LinkChange) =>
      request<InstallmentPlan>(
        linkPath(planId, fingerprint),
        number === null
          ? { method: 'DELETE' }
          : { method: 'PUT', body: JSON.stringify({ number }) },
      ),
    onSuccess: invalidate,
  })
}
