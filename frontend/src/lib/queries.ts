// Shared TanStack Query queries. The keys are public so the screens that write (rates,
// corrections) invalidate what changes.
import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  type Account,
  type BatchBody,
  type BatchResult,
  type Candidate,
  type AnswerAction,
  type CashBox,
  type CashConcept,
  type CashCount,
  type CashEntryBody,
  type ScheduleBody,
  type Category,
  type CategoryBody,
  type CategoryPatch,
  type Comparison,
  type DepositBody,
  type DismissResult,
  type EditBody,
  type ExchangeInfo,
  type Insight,
  type Interest,
  type Investment,
  type JoinBody,
  type InvestmentList,
  type InvestmentPatch,
  type InvestmentRef,
  type InvestmentRole,
  type KeywordPreview,
  type MarkBody,
  type MonthOption,
  type OneOffSuggestion,
  type Pending,
  type Recurring,
  type ReviewItem,
  type ProvisionalDecision,
  type ReceiptLink,
  type ReviewKind,
  type ReviewMark,
  type RoleBody,
  type SavedRate,
  type Summary,
  type Transactions,
  type Tx,
  type TxRecurring,
  type TxRecurringBody,
  ApiError,
  request,
  requestText,
} from './api'
import { type Selection, selectionParam, withAccounts } from './accountFilter'
import { dismissPath } from './oneOffs'
import { type Dossier, dossierPath, hashFrom, pastedBody } from './claude'
import { insightPath } from './insights'
import { type Range, rangeQuery } from './reports'
import { reviewPath } from './review'
import { apiPath, type ListFilters } from './transactions'

/** Root of the budget and reserve keys (`budgetQueries.budgetKeys.all`). */
const BUDGET_KEY = ['budget'] as const

/** Key part for the selected accounts ("all" without a selection). */
function scope(selection: Selection): string {
  return selectionParam(selection) ?? 'all'
}

export const queryKeys = {
  monthsAll: ['months'] as const,
  months: (selection: Selection) => ['months', scope(selection)] as const,
  summaries: ['summary'] as const,
  summary: (month: string, selection: Selection) => ['summary', month, scope(selection)] as const,
  transactions: ['transactions'] as const,
  transactionList: (month: string, filters: ListFilters) =>
    [
      'transactions',
      month,
      scope(filters.accounts),
      filters.category,
      filters.q.trim(),
      filters.kind,
      filters.shared,
      filters.provisional,
    ] as const,
  accounts: ['accounts'] as const,
  categories: ['categories'] as const,
  recurringAll: ['recurring'] as const,
  recurring: (month: string | null, selection: Selection) =>
    ['recurring', month ?? 'no-month', scope(selection)] as const,
  oneOffsAll: ['one-offs'] as const,
  oneOffs: (month: string, selection: Selection) => ['one-offs', month, scope(selection)] as const,
  insightsAll: ['insights'] as const,
  insight: (month: string) => ['insights', month] as const,
  claudeInstruction: ['dossier', 'prompt'] as const,
  dossier: (month: string, selection: Selection) => ['dossier', month, scope(selection)] as const,
  compareAll: ['compare'] as const,
  compare: (range: Range, selection: Selection) =>
    ['compare', range.from ?? '', range.to ?? '', scope(selection)] as const,
  reviewAll: ['review'] as const,
  review: (month: string, selection: Selection) => ['review', month, scope(selection)] as const,
  reviewHistory: (selection: Selection, kind: ReviewKind | null) =>
    ['review', 'history', scope(selection), kind ?? 'all'] as const,
  interestAll: ['interest'] as const,
  interest: (year: number, selection: Selection) => ['interest', year, scope(selection)] as const,
  pendingAll: ['pending'] as const,
  pending: (selection: Selection) => ['pending', scope(selection)] as const,
}

/** Months with data, newest to oldest; which one is in progress depends on the selected
 * accounts. When the selection changes, the previous ones stay visible. */
export function useMonths(selection: Selection = null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.months(selection),
    queryFn: () => request<MonthOption[]>(withAccounts('/api/months', selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** How long an answer fetched ahead of the screen that shows it counts as fresh: that screen
 * then uses it as it is, without asking again. Short on purpose: after it, what is in the cache
 * still shows at once and is refreshed behind. */
export const FRESH_MS = 10_000

/** The month's summary for the selected accounts (shared by the screen and what is fetched
 * ahead: `summaryPrefetch`). */
export function summaryOptions(month: string, selection: Selection = null) {
  return queryOptions({
    queryKey: queryKeys.summary(month, selection),
    queryFn: () =>
      request<Summary>(withAccounts(`/api/summary?month=${encodeURIComponent(month)}`, selection)),
    staleTime: FRESH_MS,
  })
}

/** Summary of the month for the selected accounts; while another loads the previous one stays. */
export function useSummary(month: string | null, selection: Selection = null) {
  return useQuery({
    ...summaryOptions(month ?? '', selection),
    enabled: month !== null,
    placeholderData: keepPreviousData,
  })
}

/** Saves the manual rate of `month`. A rate backs up later months, so every summary, the
 * transactions, the recurring charges and the year's interest are invalidated (they all carry
 * RD$ amounts). */
export function useSaveRate(month: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (value: string) =>
      request<SavedRate>(`/api/rates/${encodeURIComponent(month)}`, {
        method: 'PUT',
        body: JSON.stringify({ value }),
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.summaries }),
        client.invalidateQueries({ queryKey: queryKeys.transactions }),
        client.invalidateQueries({ queryKey: queryKeys.recurringAll }),
        client.invalidateQueries({ queryKey: queryKeys.interestAll }),
        client.invalidateQueries({ queryKey: queryKeys.compareAll }),
        client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
        client.invalidateQueries({ queryKey: queryKeys.pendingAll }),
        client.invalidateQueries({ queryKey: BUDGET_KEY }),
      ]),
  })
}

/** Interest paid in `year` and the next payment that avoids it. When the year changes the
 * previous one stays visible. */
export function useInterest(year: number, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.interest(year, selection),
    queryFn: () => request<Interest>(withAccounts(`/api/interest?year=${year}`, selection)),
    placeholderData: keepPreviousData,
  })
}

/** Who owes you and whom you owe (all months) in the selected accounts; when the selection
 * changes the previous data stays visible. Every link change refetches it. */
export function usePending(selection: Selection = null, enabled = true) {
  return useQuery({
    enabled,
    queryKey: queryKeys.pending(selection),
    queryFn: () => request<Pending>(withAccounts('/api/pending', selection)),
    placeholderData: keepPreviousData,
  })
}

/** Transactions of the month with the filters; when a filter changes the previous list stays. */
export function useTransactions(month: string | null, filters: ListFilters) {
  return useQuery({
    queryKey: queryKeys.transactionList(month ?? '', filters),
    queryFn: () => request<Transactions>(apiPath(month ?? '', filters)),
    enabled: month !== null,
    placeholderData: keepPreviousData,
  })
}

/** Accounts (for the filter labels). */
export function useAccounts() {
  return useQuery({
    queryKey: queryKeys.accounts,
    queryFn: () => request<Account[]>('/api/accounts'),
  })
}

/** Categories (hidden ones too), with their kind, color and keywords. They change only when
 * edited or when transactions are corrected (the year's count): they are invalidated there. */
export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: () => request<Category[]>('/api/categories'),
    staleTime: Infinity,
  })
}

/** Everything that shows categories or amounts per category. */
function invalidateCategorized(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.categories }),
    client.invalidateQueries({ queryKey: queryKeys.transactions }),
    client.invalidateQueries({ queryKey: queryKeys.summaries }),
    client.invalidateQueries({ queryKey: queryKeys.recurringAll }),
    client.invalidateQueries({ queryKey: queryKeys.oneOffsAll }),
    client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
    client.invalidateQueries({ queryKey: queryKeys.compareAll }),
    client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
    client.invalidateQueries({ queryKey: queryKeys.pendingAll }),
    // Budget and reserves (`budgetQueries`): their keys live under ['budget'], also each
    // transaction's "Reserve" section.
    client.invalidateQueries({ queryKey: BUDGET_KEY }),
  ])
}

/** Creates a category; returns the new one (with its id). */
export function useCreateCategory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CategoryBody) =>
      request<Category>('/api/categories', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Renames, recolors, hides, or changes the kind or keywords of a category. */
export function useUpdateCategory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: CategoryPatch }) =>
      request<Category>(`/api/categories/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Deletes a user category; whatever used it moves to `reassignTo`. */
export function useDeleteCategory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reassignTo }: { id: number; reassignTo: number | null }) =>
      request<void>(
        reassignTo === null
          ? `/api/categories/${id}`
          : `/api/categories/${id}?reassign_to=${reassignTo}`,
        { method: 'DELETE' },
      ),
    onSuccess: () => invalidateCategorized(client),
  })
}

/** What saving `keywords` on category `id` would move (saves nothing). */
export function useKeywordPreview(id: number, keywords: readonly string[], enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.categories, 'preview', id, ...keywords] as const,
    queryFn: () =>
      request<KeywordPreview>(`/api/categories/${id}/preview`, {
        method: 'POST',
        body: JSON.stringify({ keywords }),
      }),
    enabled,
    placeholderData: keepPreviousData,
  })
}

export interface EditVars {
  fingerprint: string
  body: EditBody
}

/** Corrects a transaction (or its whole merchant). Lists, summaries, recurring charges (the
 * category decides the group) and one-off suggestions change: they are invalidated. */
export function useEditTransaction() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ fingerprint, body }: EditVars) =>
      request<Tx>(`/api/transactions/${encodeURIComponent(fingerprint)}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Changes the category of several transactions at once (a single log entry). Same as a
 * correction and, because of the manual entries, the cash box. */
export function useBatchCategory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: BatchBody) =>
      request<BatchResult>('/api/transactions', { method: 'PATCH', body: JSON.stringify(body) }),
    onSuccess: () =>
      Promise.all([
        invalidateCategorized(client),
        client.invalidateQueries({ queryKey: CASH_BOX_KEY }),
      ]),
  })
}

/** Purchases of the month that look like one-off expenses. */
export function useOneOffSuggestions(month: string, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.oneOffs(month, selection),
    queryFn: () =>
      request<OneOffSuggestion[]>(
        withAccounts(`/api/one-off-suggestions?month=${encodeURIComponent(month)}`, selection),
      ),
  })
}

/** "Not one-off" (or undoing it): changes the suggestions and the list's marks. */
export function useDismissOneOff() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ fingerprint, dismissed }: { fingerprint: string; dismissed: boolean }) =>
      request<DismissResult>(dismissPath(fingerprint), {
        method: 'PUT',
        body: JSON.stringify({ dismissed }),
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.oneOffsAll }),
        client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
        client.invalidateQueries({ queryKey: queryKeys.transactions }),
        client.invalidateQueries({ queryKey: queryKeys.summaries }),
      ]),
  })
}

/** The month's items to review (pending) in the selected accounts. */
export function useReview(month: string, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.review(month, selection),
    queryFn: () =>
      request<ReviewItem[]>(withAccounts(`/api/review?month=${encodeURIComponent(month)}`, selection)),
  })
}

/** "To review" history (pending and reviewed) of the last months. */
export function useReviewHistory(selection: Selection = null, kind: ReviewKind | null = null) {
  return useQuery({
    queryKey: queryKeys.reviewHistory(selection, kind),
    queryFn: () =>
      request<ReviewItem[]>(
        withAccounts(kind ? `/api/review/history?kind=${kind}` : '/api/review/history', selection),
      ),
    placeholderData: keepPreviousData,
  })
}

/** "I reviewed it" (or undoing it). For a one-off expense it is the usual dismissal: the
 * suggestions and the list's marks change too. */
export function useMarkReviewed() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, fingerprint, reviewed }: ReviewMark) =>
      request<ReviewMark>(reviewPath(kind, fingerprint), {
        method: 'PUT',
        body: JSON.stringify({ reviewed }),
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
        client.invalidateQueries({ queryKey: queryKeys.oneOffsAll }),
        client.invalidateQueries({ queryKey: queryKeys.transactions }),
      ]),
  })
}

/** "Discard" or "Keep" a provisional (from a bank alert) that did not show up in its statement;
 * null forgets the decision. Discarding removes it from every total: everything is refetched. */
export function useDecideProvisional() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ fingerprint, decision }: { fingerprint: string; decision: ProvisionalDecision }) =>
      request<{ fingerprint: string; decision: ProvisionalDecision }>(
        `/api/provisional/${encodeURIComponent(fingerprint)}`,
        { method: 'PUT', body: JSON.stringify({ decision }) },
      ),
    onSuccess: () => client.invalidateQueries(),
  })
}

/** "It is this one" (links the receipt to the transaction) or "it is not" (removes the link or
 * refuses the proposal; the pair is not offered again). Either way another receipt may now be
 * linked on its own. A receipt changes no figure: only the transactions (with their log and
 * history) and To review are refetched. */
export function useDecideReceipt() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ receipt_id, fingerprint, linked }: ReceiptLink) =>
      request<ReceiptLink>(
        `/api/receipts/${receipt_id}/transactions/${encodeURIComponent(fingerprint)}`,
        { method: linked ? 'PUT' : 'DELETE' },
      ),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.transactions }),
        client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
      ]),
  })
}

/** Recurring charges; with `month` it also brings that month's notices. When the month changes
 * the previous one stays visible. */
export function useRecurring(month: string | null, selection: Selection = null, enabled = true) {
  return useQuery({
    enabled,
    queryKey: queryKeys.recurring(month, selection),
    queryFn: () =>
      request<Recurring>(
        withAccounts(
          month === null ? '/api/recurring' : `/api/recurring?month=${encodeURIComponent(month)}`,
          selection,
        ),
      ),
    placeholderData: keepPreviousData,
  })
}

/** Marks a recurring charge. The PUT response carries no month's notices, so the cache is not
 * written: every recurring query is invalidated and refetched. */
export function useMarkRecurring() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: MarkBody) =>
      request<Recurring>('/api/recurring/mark', { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.recurringAll }),
  })
}

/** What a join or "It is recurring…" changes: recurring charges, transactions (and with them
 * the log and the detail's recurring state), one-off expenses and "To review". */
function invalidateRecurring(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.recurringAll }),
    client.invalidateQueries({ queryKey: queryKeys.transactions }),
    client.invalidateQueries({ queryKey: queryKeys.oneOffsAll }),
    client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
  ])
}

/** "Join with…": merges a recurring charge's series with another (or with a provider). */
export function useJoinRecurring() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: JoinBody) =>
      request<Recurring>('/api/recurring/join', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => invalidateRecurring(client),
  })
}

/** "Separate": the merchant goes alone again. */
export function useSeparateRecurring() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (merchant: string) =>
      request<Recurring>('/api/recurring/separate', {
        method: 'POST',
        body: JSON.stringify({ merchant }),
      }),
    onSuccess: () => invalidateRecurring(client),
  })
}

/** What the transaction is for Recurring (whether it can be marked or where it is). */
export function useTxRecurring(fingerprint: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: [...queryKeys.transactions, 'recurring', fingerprint] as const,
    queryFn: () => request<TxRecurring>(txPath(fingerprint, '/recurring')),
  })
}

/** "It is recurring…" from a transaction's detail. */
export function useMarkTxRecurring() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ fingerprint, body }: { fingerprint: string; body: TxRecurringBody }) =>
      request<TxRecurring>(txPath(fingerprint, '/recurring'), {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => invalidateRecurring(client),
  })
}

function txPath(fingerprint: string, rest = ''): string {
  return `/api/transactions/${encodeURIComponent(fingerprint)}${rest}`
}

/** A single transaction (the same row as the list, with its links): a link's screen loads it
 * without the list. */
export function useTransaction(fingerprint: string) {
  return useQuery({
    queryKey: transactionKey(fingerprint),
    queryFn: () => request<Tx>(txPath(fingerprint)),
    // A fingerprint that does not exist will not appear by retrying.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  })
}

/** Key of a single transaction (under `transactions`: every write refetches it). */
export function transactionKey(fingerprint: string) {
  return [...queryKeys.transactions, 'one', fingerprint] as const
}

/** Investments: all of them (of the selected accounts) and their totals. Under `transactions`:
 * every change of a link or a rate refetches it. */
export function useInvestmentList(selection: Selection, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'investments', scope(selection)] as const,
    queryFn: () => request<InvestmentList>(withAccounts('/api/investments', selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** One investment (its management screen). */
export function useInvestment(id: number | null) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'investment', id ?? 0] as const,
    queryFn: () => request<Investment>(`/api/investments/${id}`),
    enabled: id !== null,
    // A 404 is an investment without visible contributions (dormant): retrying will not bring it.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  })
}

/** The investments something can be added to ("Add to an existing one"); with `includeLost`
 * (for a credit), also the written-off ones. */
export function useOpenInvestments(enabled: boolean, includeLost = false) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'open-investments', includeLost] as const,
    queryFn: () =>
      request<InvestmentRef[]>(
        includeLost ? '/api/investments/open?include_lost=true' : '/api/investments/open',
      ),
    enabled,
  })
}

/** What can be added to an investment: debits (`contribution`) or credits (`credit`). */
export function useInvestmentCandidates(
  id: number,
  kind: 'contribution' | 'credit',
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'investment-candidates', id, kind] as const,
    queryFn: () => request<Candidate[]>(`/api/investments/${id}/candidates?kind=${kind}`),
    enabled,
  })
}

export type InvestmentChange =
  | { action: 'create'; fingerprint: string; withWhom?: string | null; name?: string | null }
  | { action: 'patch'; id: number; body: InvestmentPatch }
  | {
      action: 'add'
      id: number
      fingerprint: string
      role: InvestmentRole
      capitalCents?: number | null
    }
  | { action: 'role'; id: number; fingerprint: string; body: RoleBody }
  | { action: 'remove'; id: number; fingerprint: string }

function investmentRequest(change: InvestmentChange): Promise<Investment | undefined> {
  const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })
  const member = (id: number, fingerprint: string) =>
    `/api/investments/${id}/members/${encodeURIComponent(fingerprint)}`
  switch (change.action) {
    case 'create':
      return request<Investment>(
        '/api/investments',
        json('POST', {
          fingerprint: change.fingerprint,
          with_whom: change.withWhom ?? null,
          name: change.name ?? null,
        }),
      )
    case 'patch':
      return request<Investment>(`/api/investments/${change.id}`, json('PATCH', change.body))
    case 'add':
      return request<Investment>(
        `/api/investments/${change.id}/members`,
        json('POST', {
          fingerprint: change.fingerprint,
          role: change.role,
          ...(change.capitalCents ? { capital_cents: change.capitalCents } : {}),
        }),
      )
    case 'role':
      return request<Investment>(member(change.id, change.fingerprint), json('PUT', change.body))
    case 'remove':
      // With the last contribution the investment is deleted (204, no body).
      return request<Investment | undefined>(member(change.id, change.fingerprint), {
        method: 'DELETE',
      })
  }
}

/** Creates an investment, adds or removes entries, changes a credit's role, renames it or
 * writes it off: everything that shows amounts or categories changes and is refetched. */
export function useChangeInvestment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: investmentRequest,
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Possible legs of a currency exchange for this transaction. */
export function useExchangeCandidates(fingerprint: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'exchange-candidates', fingerprint] as const,
    queryFn: () => request<Candidate[]>(txPath(fingerprint, '/exchange-candidates')),
    enabled,
  })
}

export type ExchangeChange =
  | { action: 'create'; fingerprints: string[]; agreedRate?: string | null }
  | { action: 'add'; id: number; fingerprints: string[] }
  | { action: 'remove'; id: number; fingerprint: string }
  | { action: 'update'; id: number; agreedRate?: string | null; closed?: boolean }
  | { action: 'delete'; id: number }

function exchangeRequest(change: ExchangeChange): Promise<ExchangeInfo | undefined> {
  switch (change.action) {
    case 'create':
      return request<ExchangeInfo>('/api/exchanges', {
        method: 'POST',
        body: JSON.stringify({
          fingerprints: change.fingerprints,
          ...(change.agreedRate ? { agreed_rate: change.agreedRate } : {}),
        }),
      })
    case 'add':
      return request<ExchangeInfo>(`/api/exchanges/${change.id}/legs`, {
        method: 'POST',
        body: JSON.stringify({ fingerprints: change.fingerprints }),
      })
    case 'remove':
      return request<ExchangeInfo | undefined>(
        `/api/exchanges/${change.id}/legs/${encodeURIComponent(change.fingerprint)}`,
        { method: 'DELETE' },
      )
    case 'delete':
      return request<undefined>(`/api/exchanges/${change.id}`, { method: 'DELETE' })
    case 'update':
      return request<ExchangeInfo>(`/api/exchanges/${change.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          ...(change.agreedRate !== undefined && { agreed_rate: change.agreedRate }),
          ...(change.closed !== undefined && { closed: change.closed }),
        }),
      })
  }
}

/** Creates an exchange, adds or removes legs, sets the rate or closes it. Everything that shows
 * amounts or categories changes: it is invalidated. */
export function useChangeExchange() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: exchangeRequest,
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Compare months: categories × months of the range (by default, the 12 most recent). */
export function useComparison(range: Range, selection: Selection = null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.compare(range, selection),
    queryFn: () =>
      request<Comparison>(withAccounts(`/api/reports/compare${rangeQuery(range)}`, selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** Saved analyses, from the most recent month to the oldest. */
export function useInsights() {
  return useQuery({
    queryKey: queryKeys.insightsAll,
    queryFn: () => request<Insight[]>('/api/insights'),
  })
}

/** The month's analysis; null if there is none. */
export function useInsight(month: string) {
  return useQuery({
    queryKey: queryKeys.insight(month),
    queryFn: async () => {
      try {
        return await request<Insight>(insightPath(month))
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
  })
}

/** Saves the text of a month's analysis (edits or creates it). */
export function useSaveInsight() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ month, text }: { month: string; text: string }) =>
      request<Insight>(insightPath(month), { method: 'PUT', body: JSON.stringify({ text }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
  })
}

/** The fixed instruction of "Copy for Claude" (it does not change while the server runs). */
export function useClaudeInstruction() {
  return useQuery({
    queryKey: queryKeys.claudeInstruction,
    queryFn: async () => (await request<{ text: string }>('/api/dossier/prompt')).text,
    staleTime: Infinity,
  })
}

/** The month's dossier (Markdown and fingerprint) with the selected accounts: requested when the
 * dialog opens and not refetched while it is open (what is copied must be what is shown). */
export function useDossier(month: string, selection: Selection) {
  return useQuery({
    queryKey: queryKeys.dossier(month, selection),
    queryFn: async (): Promise<Dossier> => {
      const { text, headers } = await requestText(dossierPath(month, selection))
      return { markdown: text, fingerprint: hashFrom(headers) }
    },
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

interface PastedSave {
  month: string
  text: string
  selection: Selection
  /** The fingerprint of the dossier that was copied (null: today's). */
  fingerprint: string | null
}

/** Saves Claude's pasted answer as the month's new analysis (replaces the saved one). */
export function useSavePastedInsight() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ month, text, selection, fingerprint }: PastedSave) =>
      request<Insight>(insightPath(month), {
        method: 'PUT',
        body: JSON.stringify(pastedBody(text, selection, fingerprint)),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
  })
}

/** Deletes a month's analysis. */
export function useDeleteInsight() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (month: string) => request<void>(insightPath(month), { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
  })
}

const CASH_BOX_KEY = [...queryKeys.transactions, 'cash-box'] as const

/** The cash box: balance per currency and its entries. Under `transactions`: every change of a
 * link, a correction or a rate refetches it. */
export function useCashBox() {
  return useQuery({
    queryKey: CASH_BOX_KEY,
    queryFn: () => request<CashBox>('/api/cash-box'),
  })
}

/** The concepts written before (autocomplete of the cash forms). */
export function useCashConcepts(enabled = true) {
  return useQuery({
    queryKey: [...CASH_BOX_KEY, 'concepts'],
    queryFn: () => request<CashConcept[]>('/api/cash-box/concepts'),
    enabled,
  })
}

export type CashBoxChange =
  | { action: 'add'; body: CashEntryBody }
  | { action: 'schedule-add'; body: ScheduleBody }
  | { action: 'schedule-update'; id: number; body: ScheduleBody }
  | { action: 'schedule-pause'; id: number; paused: boolean }
  | { action: 'schedule-delete'; id: number }
  | { action: 'answer'; id: number; answer: AnswerAction; amount_cents?: number }
  | { action: 'reconcile'; counts: CashCount[] }
  | { action: 'update'; id: number; body: Omit<CashEntryBody, 'kind'> }
  | { action: 'delete'; id: number }
  | { action: 'store'; fingerprint: string }
  | { action: 'unstore'; fingerprint: string }
  | { action: 'deposit'; fingerprint: string; body: DepositBody }
  | { action: 'undeposit'; fingerprint: string }

function cashBoxRequest(change: CashBoxChange): Promise<CashBox | Tx | undefined> {
  const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })
  const fp = (value: string) => encodeURIComponent(value)
  switch (change.action) {
    case 'add':
      return request<CashBox>('/api/cash-box/entries', json('POST', change.body))
    case 'schedule-add':
      return request<CashBox>('/api/cash-box/schedules', json('POST', change.body))
    case 'schedule-update':
      return request<CashBox>(`/api/cash-box/schedules/${change.id}`, json('PUT', change.body))
    case 'schedule-pause':
      return request<CashBox>(
        `/api/cash-box/schedules/${change.id}/paused`,
        json('PUT', { paused: change.paused }),
      )
    case 'schedule-delete':
      return request<CashBox>(`/api/cash-box/schedules/${change.id}`, { method: 'DELETE' })
    case 'answer':
      return request<CashBox>(
        `/api/cash-box/occurrences/${change.id}`,
        json('POST', { action: change.answer, amount_cents: change.amount_cents ?? null }),
      )
    case 'reconcile':
      return request<CashBox>('/api/cash-box/reconcile', json('POST', { counts: change.counts }))
    case 'update':
      return request<CashBox>(`/api/cash-box/entries/${change.id}`, json('PUT', change.body))
    case 'delete':
      return request<CashBox>(`/api/cash-box/entries/${change.id}`, { method: 'DELETE' })
    case 'store':
      return request<Tx>(`/api/cash-box/stored/${fp(change.fingerprint)}`, { method: 'PUT' })
    case 'unstore':
      // No body (204) if the withdrawal no longer appears.
      return request<Tx | undefined>(`/api/cash-box/stored/${fp(change.fingerprint)}`, {
        method: 'DELETE',
      })
    case 'deposit':
      return request<Tx>(
        `/api/cash-box/deposits/${fp(change.fingerprint)}`,
        json('PUT', change.body),
      )
    case 'undeposit':
      return request<Tx | undefined>(`/api/cash-box/deposits/${fp(change.fingerprint)}`, {
        method: 'DELETE',
      })
  }
}

/** Records, edits or deletes a cash-box entry, or marks a stored withdrawal or a deposit:
 * everything that shows amounts or categories changes, and so does the account list (the cash
 * box appears once used). */
export function useChangeCashBox() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: cashBoxRequest,
    onSuccess: () =>
      Promise.all([
        invalidateCategorized(client),
        client.invalidateQueries({ queryKey: queryKeys.accounts }),
        client.invalidateQueries({ queryKey: queryKeys.monthsAll }),
      ]),
  })
}
