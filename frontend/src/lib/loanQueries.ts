// Loans: their cards, the charges one can link by hand, and the writes. A write changes the
// rows' tags and To review: they are invalidated with the loans.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Loan, type LoanBody, type LoanCandidate, type LoanEdit, request } from './api'
import { queryKeys } from './queries'

export const loanKeys = {
  all: ['loans'] as const,
  candidates: (id: number, q: string) => ['loans', 'candidates', id, q] as const,
}

function loanPath(id: number): string {
  return `/api/loans/${id}`
}

export function useLoans(enabled = true) {
  return useQuery({ enabled, queryKey: loanKeys.all, queryFn: () => request<Loan[]>('/api/loans') })
}

/** Recent charges in the loan's currency, not in any loan (`q` filters by description). */
export function useLoanCandidates(id: number, q: string, enabled = true) {
  const query = q.trim() === '' ? '' : `?q=${encodeURIComponent(q.trim())}`
  return useQuery({
    enabled,
    queryKey: loanKeys.candidates(id, q.trim()),
    queryFn: () => request<LoanCandidate[]>(`${loanPath(id)}/candidates${query}`),
  })
}

function useInvalidateLoans() {
  const client = useQueryClient()
  return () =>
    Promise.all(
      [loanKeys.all, queryKeys.transactions, queryKeys.reviewAll].map((queryKey) =>
        client.invalidateQueries({ queryKey }),
      ),
    )
}

function useLoanWrite<T>(call: (input: T) => Promise<Loan | void>) {
  const invalidate = useInvalidateLoans()
  return useMutation({ mutationFn: call, onSuccess: invalidate })
}

/** "New loan": every charge with its number is linked at once. */
export function useCreateLoan() {
  return useLoanWrite((body: LoanBody) =>
    request<Loan>('/api/loans', { method: 'POST', body: JSON.stringify(body) }),
  )
}

export function useEditLoan() {
  return useLoanWrite(({ id, body }: { id: number; body: LoanEdit }) =>
    request<Loan>(loanPath(id), { method: 'PATCH', body: JSON.stringify(body) }),
  )
}

/** "Delete loan": the payments stay as they are. */
export function useDeleteLoan() {
  return useLoanWrite((id: number) => request<void>(loanPath(id), { method: 'DELETE' }))
}

export interface DatedChange {
  id: number
  day: string
  /** The new value (rate in hundredths of a percent, balance in cents); null removes it. */
  value: number | null
}

/** A rate from a day on (or its removal). */
export function useLoanRate() {
  return useLoanWrite(({ id, day, value }: DatedChange) =>
    request<Loan>(
      `${loanPath(id)}/rates/${day}`,
      value === null
        ? { method: 'DELETE' }
        : { method: 'PUT', body: JSON.stringify({ rate_bp: value }) },
    ),
  )
}

/** What the bank charges each month from a day on (or its removal). */
export function useLoanInstallment() {
  return useLoanWrite(({ id, day, value }: DatedChange) =>
    request<Loan>(
      `${loanPath(id)}/installments/${day}`,
      value === null
        ? { method: 'DELETE' }
        : { method: 'PUT', body: JSON.stringify({ installment_cents: value }) },
    ),
  )
}

/** The real balance on a day, from the bank (or its removal). */
export function useLoanBalance() {
  return useLoanWrite(({ id, day, value }: DatedChange) =>
    request<Loan>(
      `${loanPath(id)}/balances/${day}`,
      value === null
        ? { method: 'DELETE' }
        : { method: 'PUT', body: JSON.stringify({ balance_cents: value }) },
    ),
  )
}

export interface PaymentChange {
  id: number
  fingerprint: string
  linked: boolean // true: "it is a payment of this loan"; false: "it is not"
}

export function useLoanPayment() {
  return useLoanWrite(({ id, fingerprint, linked }: PaymentChange) =>
    request<Loan>(`${loanPath(id)}/transactions/${encodeURIComponent(fingerprint)}`, {
      method: linked ? 'PUT' : 'DELETE',
    }),
  )
}
