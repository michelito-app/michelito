// Consultas compartidas con TanStack Query. Las claves son públicas para que las pantallas
// que escriben (tasas, correcciones) invaliden lo que cambia.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type Account,
  type BatchBody,
  type BatchResult,
  type Candidate,
  type CashBox,
  type CashEntryBody,
  type Category,
  type CategoryBody,
  type CategoryPatch,
  type Comparison,
  type DepositBody,
  type DismissResult,
  type EditBody,
  type ExchangeInfo,
  type GroupPatch,
  type GroupRef,
  type ManualBody,
  type ReimbursementCandidates,
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
  type ReviewKind,
  type ReviewMark,
  type RoleBody,
  type SavedRate,
  type SharedInfo,
  type SharedList,
  type SplitBody,
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

/** La raíz de las claves del presupuesto y las reservas (`budgetQueries.budgetKeys.all`). */
const BUDGET_KEY = ['budget'] as const

/** Parte de la clave para las cuentas elegidas ("todas" si no hay selección). */
function scope(selection: Selection): string {
  return selectionParam(selection) ?? 'todas'
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
    ] as const,
  accounts: ['accounts'] as const,
  categories: ['categories'] as const,
  recurringAll: ['recurring'] as const,
  recurring: (month: string | null, selection: Selection) =>
    ['recurring', month ?? 'sin-mes', scope(selection)] as const,
  oneOffsAll: ['one-offs'] as const,
  oneOffs: (month: string, selection: Selection) => ['one-offs', month, scope(selection)] as const,
  insightsAll: ['insights'] as const,
  insight: (month: string) => ['insights', month] as const,
  claudeInstruction: ['dossier', 'instruccion'] as const,
  dossier: (month: string, selection: Selection) => ['dossier', month, scope(selection)] as const,
  compareAll: ['compare'] as const,
  compare: (range: Range, selection: Selection) =>
    ['compare', range.from ?? '', range.to ?? '', scope(selection)] as const,
  reviewAll: ['review'] as const,
  review: (month: string, selection: Selection) => ['review', month, scope(selection)] as const,
  reviewHistory: (selection: Selection, kind: ReviewKind | null) =>
    ['review', 'historial', scope(selection), kind ?? 'todos'] as const,
  interestAll: ['interest'] as const,
  interest: (year: number, selection: Selection) => ['interest', year, scope(selection)] as const,
  pendingAll: ['pending'] as const,
  pending: (selection: Selection) => ['pending', scope(selection)] as const,
}

/** Meses con datos, del más nuevo al más viejo; cuál está en curso depende de las cuentas
 * elegidas. Al cambiar de selección se siguen viendo los anteriores. */
export function useMonths(selection: Selection = null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.months(selection),
    queryFn: () => request<MonthOption[]>(withAccounts('/api/months', selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** Resumen del mes de las cuentas elegidas; mientras carga otro se sigue viendo el anterior. */
export function useSummary(month: string | null, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.summary(month ?? '', selection),
    queryFn: () =>
      request<Summary>(
        withAccounts(`/api/summary?month=${encodeURIComponent(month ?? '')}`, selection),
      ),
    enabled: month !== null,
    placeholderData: keepPreviousData,
  })
}

/** Guarda la tasa manual de `month`. Una tasa sirve de respaldo a meses posteriores, así que
 * se invalidan todos los resúmenes, las transacciones, los recurrentes y los intereses del año
 * (todos llevan montos en RD$). */
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

/** Intereses pagados en `year` y el próximo pago para no generarlos. Al cambiar de año se
 * sigue viendo el anterior. */
export function useInterest(year: number, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.interest(year, selection),
    queryFn: () => request<Interest>(withAccounts(`/api/interest?year=${year}`, selection)),
    placeholderData: keepPreviousData,
  })
}

/** Quién te debe y a quién debes (todos los meses) en las cuentas elegidas; al cambiar de
 * selección se sigue viendo lo anterior. Cada vínculo que cambia lo vuelve a pedir. */
export function usePending(selection: Selection = null, enabled = true) {
  return useQuery({
    enabled,
    queryKey: queryKeys.pending(selection),
    queryFn: () => request<Pending>(withAccounts('/api/pending', selection)),
    placeholderData: keepPreviousData,
  })
}

/** Transacciones del mes con los filtros; al cambiar de filtro se sigue viendo la lista previa. */
export function useTransactions(month: string | null, filters: ListFilters) {
  return useQuery({
    queryKey: queryKeys.transactionList(month ?? '', filters),
    queryFn: () => request<Transactions>(apiPath(month ?? '', filters)),
    enabled: month !== null,
    placeholderData: keepPreviousData,
  })
}

/** Cuentas (para las etiquetas del filtro). */
export function useAccounts() {
  return useQuery({
    queryKey: queryKeys.accounts,
    queryFn: () => request<Account[]>('/api/accounts'),
  })
}

/** Categorías (también las ocultas), con su tipo, color y palabras clave. Cambian solo al
 * editarlas o al corregir transacciones (la cuenta del año): ahí se invalidan. */
export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: () => request<Category[]>('/api/categories'),
    staleTime: Infinity,
  })
}

/** Todo lo que muestra categorías o montos por categoría. */
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
    // Presupuesto y reservas (`budgetQueries`): sus claves van bajo ['budget'], también la
    // sección «Reserva» de cada transacción.
    client.invalidateQueries({ queryKey: BUDGET_KEY }),
  ])
}

/** Crea una categoría; devuelve la nueva (con su id). */
export function useCreateCategory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CategoryBody) =>
      request<Category>('/api/categories', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Renombra, recolorea, oculta, cambia el tipo o las palabras clave de una categoría. */
export function useUpdateCategory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: CategoryPatch }) =>
      request<Category>(`/api/categories/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Borra una categoría del usuario; lo que la usaba pasa a `reassignTo`. */
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

/** Qué movería guardar `keywords` en la categoría `id` (no guarda nada). */
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

/** Corrige una transacción (o todo su comercio). Cambia listas, resúmenes, recurrentes (la
 * categoría decide el grupo) y sugerencias de gasto único: se invalidan. */
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

/** Cambia la categoría de varias transacciones a la vez (una sola entrada de bitácora). Lo
 * mismo que una corrección y, por los movimientos a mano, la caja fuerte. */
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

/** Compras del mes que parecen gastos únicos. */
export function useOneOffSuggestions(month: string, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.oneOffs(month, selection),
    queryFn: () =>
      request<OneOffSuggestion[]>(
        withAccounts(`/api/one-off-suggestions?month=${encodeURIComponent(month)}`, selection),
      ),
  })
}

/** "No es único" (o deshacerlo): cambia las sugerencias y las marcas de la lista. */
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

/** Lo del mes para revisar (pendiente) en las cuentas elegidas. */
export function useReview(month: string, selection: Selection = null) {
  return useQuery({
    queryKey: queryKeys.review(month, selection),
    queryFn: () =>
      request<ReviewItem[]>(withAccounts(`/api/review?month=${encodeURIComponent(month)}`, selection)),
  })
}

/** Historial de «Para revisar» (pendiente y revisado) de los últimos meses. */
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

/** "Ya lo revisé" (o deshacerlo). En un gasto único es el descarte de siempre: cambian también
 * las sugerencias y las marcas de la lista. */
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

/** Cargos recurrentes; con `month` trae también los avisos de ese mes. Al cambiar de mes se
 * sigue viendo el anterior. */
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

/** Marca un recurrente. La respuesta del PUT no trae los avisos de ningún mes, así que no se
 * escribe en la caché: se invalidan todas las consultas de recurrentes y se vuelven a pedir. */
export function useMarkRecurring() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: MarkBody) =>
      request<Recurring>('/api/recurring/mark', { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.recurringAll }),
  })
}

/** Lo que cambia una unión o «Es recurrente…»: recurrentes, transacciones (y con ellas la
 * bitácora y el estado de recurrente del detalle), gastos únicos y «Para revisar». */
function invalidateRecurring(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.recurringAll }),
    client.invalidateQueries({ queryKey: queryKeys.transactions }),
    client.invalidateQueries({ queryKey: queryKeys.oneOffsAll }),
    client.invalidateQueries({ queryKey: queryKeys.reviewAll }),
  ])
}

/** «Unir con…»: junta la serie de un recurrente con otra (o con un proveedor). */
export function useJoinRecurring() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: JoinBody) =>
      request<Recurring>('/api/recurring/join', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => invalidateRecurring(client),
  })
}

/** «Separar»: el comercio vuelve a ir solo. */
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

/** Qué es la transacción para Recurrentes (si se puede marcar o dónde está). */
export function useTxRecurring(fingerprint: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey: [...queryKeys.transactions, 'recurring', fingerprint] as const,
    queryFn: () => request<TxRecurring>(txPath(fingerprint, '/recurring')),
  })
}

/** «Es recurrente…» desde el detalle de una transacción. */
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

/** Una sola transacción (la misma fila que la lista, con sus vínculos): la pantalla de un
 * vínculo la carga sin la lista. */
export function useTransaction(fingerprint: string) {
  return useQuery({
    queryKey: transactionKey(fingerprint),
    queryFn: () => request<Tx>(txPath(fingerprint)),
    // Una huella que no existe no aparece reintentando.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  })
}

/** Clave de una sola transacción (cae bajo `transactions`: cada escritura la vuelve a pedir). */
export function transactionKey(fingerprint: string) {
  return [...queryKeys.transactions, 'one', fingerprint] as const
}

/** Créditos que pueden reembolsar el grupo de un gasto compartido (o grupos que un crédito
 * puede reembolsar) y los "dónde" ya usados. */
export function useReimbursementCandidates(fingerprint: string, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'reimbursement-candidates', fingerprint] as const,
    queryFn: () => request<ReimbursementCandidates>(txPath(fingerprint, '/reimbursement-candidates')),
    enabled,
  })
}

/** Desenlaza un crédito desde su lado, por su vínculo (sirve aunque el gasto ya no aparezca). */
export function useUnlinkCredit() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (credit: string) =>
      request<void>(`/api/reimbursements/${encodeURIComponent(credit)}`, { method: 'DELETE' }),
    onSuccess: () => invalidateCategorized(client),
  })
}

function groupPath(id: number, rest = ''): string {
  return `/api/shared/${id}${rest}`
}

/** Grupos con pendiente, los más recientes primero («Sumarlo a un grupo»). */
export function useOpenGroups(enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'open-groups'] as const,
    queryFn: () => request<GroupRef[]>('/api/shared/open'),
    enabled,
  })
}

/** Compartidos: todos los grupos (de las cuentas elegidas) y sus totales. Va bajo
 * `transactions`: cada cambio de un vínculo o de una tasa lo vuelve a pedir. */
export function useSharedList(selection: Selection, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'compartidos', scope(selection)] as const,
    queryFn: () => request<SharedList>(withAccounts('/api/shared', selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** «Nuevo grupo…»: gastos sin vínculo de los últimos 120 días, el más reciente primero. */
export function useNewGroupCandidates(selection: Selection, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'nuevo-grupo', scope(selection)] as const,
    queryFn: () => request<Candidate[]>(withAccounts('/api/shared/new-candidates', selection)),
    enabled,
  })
}

/** «Agregar otro gasto»: gastos sin vínculo cerca de los del grupo. */
export function useGroupExpenseCandidates(id: number, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'group-expenses', id] as const,
    queryFn: () => request<Candidate[]>(groupPath(id, '/expense-candidates')),
    enabled,
  })
}

/** «Agregar reembolso»: créditos que pueden reembolsar el grupo y los "dónde" ya usados. */
export function useGroupCreditCandidates(id: number, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'group-credits', id] as const,
    queryFn: () => request<ReimbursementCandidates>(groupPath(id, '/credit-candidates')),
    enabled,
  })
}

export type GroupChange =
  | { action: 'patch'; id: number; body: GroupPatch }
  | { action: 'add-expense'; id: number; fingerprint: string; split: SplitBody }
  | { action: 'split'; id: number; fingerprint: string; split: SplitBody }
  | { action: 'remove-expense'; id: number; fingerprint: string }
  | { action: 'add-credit'; id: number; credit: string }
  | { action: 'add-manual'; id: number; manual: ManualBody }
  | { action: 'remove-credit'; id: number; credit: string }
  | { action: 'remove-manual'; id: number; manualId: number }

function groupRequest(change: GroupChange): Promise<SharedInfo | undefined> {
  const id = change.id
  const fp = (value: string) => encodeURIComponent(value)
  const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })
  switch (change.action) {
    case 'patch':
      return request<SharedInfo>(groupPath(id), json('PATCH', change.body))
    case 'add-expense':
      return request<SharedInfo>(
        groupPath(id, '/expenses'),
        json('POST', { fingerprint: change.fingerprint, split: change.split }),
      )
    case 'split':
      return request<SharedInfo>(
        groupPath(id, `/expenses/${fp(change.fingerprint)}`),
        json('PUT', change.split),
      )
    case 'remove-expense':
      // Con el último gasto se borra el grupo (204, sin cuerpo).
      return request<SharedInfo | undefined>(groupPath(id, `/expenses/${fp(change.fingerprint)}`), {
        method: 'DELETE',
      })
    case 'add-credit':
      return request<SharedInfo>(
        groupPath(id, '/reimbursements'),
        json('POST', { credit: change.credit }),
      )
    case 'add-manual':
      return request<SharedInfo>(
        groupPath(id, '/reimbursements'),
        json('POST', { manual: change.manual }),
      )
    case 'remove-credit':
      return request<SharedInfo>(groupPath(id, `/reimbursements/${fp(change.credit)}`), {
        method: 'DELETE',
      })
    case 'remove-manual':
      return request<SharedInfo>(groupPath(id, `/manual/${change.manualId}`), { method: 'DELETE' })
  }
}

/** Cambia un grupo compartido (nombre, gastos, repartos, reembolsos); todo lo que depende de
 * los vínculos se vuelve a pedir. */
export function useChangeGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: groupRequest,
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Inversiones: todas (de las cuentas elegidas) y sus totales. Va bajo `transactions`: cada
 * cambio de un vínculo o de una tasa lo vuelve a pedir. */
export function useInvestmentList(selection: Selection, enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'inversiones', scope(selection)] as const,
    queryFn: () => request<InvestmentList>(withAccounts('/api/investments', selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** Una inversión (su pantalla de gestión). */
export function useInvestment(id: number | null) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'inversion', id ?? 0] as const,
    queryFn: () => request<Investment>(`/api/investments/${id}`),
    enabled: id !== null,
    // Un 404 es una inversión sin aportes a la vista (dormida): reintentar no la trae.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  })
}

/** Las inversiones a las que se puede sumar algo («Añadir a una existente»); con
 * `includeLost` (para un crédito), también las dadas por perdidas. */
export function useOpenInvestments(enabled: boolean, includeLost = false) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'inversiones-abiertas', includeLost] as const,
    queryFn: () =>
      request<InvestmentRef[]>(
        includeLost ? '/api/investments/open?include_lost=true' : '/api/investments/open',
      ),
    enabled,
  })
}

/** Lo que se puede sumar a una inversión: débitos (`contribution`) o créditos (`credit`). */
export function useInvestmentCandidates(
  id: number,
  kind: 'contribution' | 'credit',
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...queryKeys.transactions, 'inversion-candidatos', id, kind] as const,
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
      // Con el último aporte se borra la inversión (204, sin cuerpo).
      return request<Investment | undefined>(member(change.id, change.fingerprint), {
        method: 'DELETE',
      })
  }
}

/** Crea una inversión, suma o quita movimientos, cambia el tipo de un crédito, la renombra o la
 * da por perdida: todo lo que muestra montos o categorías cambia y se vuelve a pedir. */
export function useChangeInvestment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: investmentRequest,
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Patas posibles de un cambio de divisas para esta transacción. */
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

/** Crea un cambio, agrega o quita patas, fija la tasa o lo cierra. Todo lo que muestra montos
 * o categorías cambia: se invalida. */
export function useChangeExchange() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: exchangeRequest,
    onSuccess: () => invalidateCategorized(client),
  })
}

/** Comparar meses: categorías × meses del rango (por defecto, los 12 más recientes). */
export function useComparison(range: Range, selection: Selection = null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.compare(range, selection),
    queryFn: () =>
      request<Comparison>(withAccounts(`/api/reports/compare${rangeQuery(range)}`, selection)),
    enabled,
    placeholderData: keepPreviousData,
  })
}

/** Análisis guardados, del mes más reciente al más viejo. */
export function useInsights() {
  return useQuery({
    queryKey: queryKeys.insightsAll,
    queryFn: () => request<Insight[]>('/api/insights'),
  })
}

/** El análisis del mes; null si no hay. */
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

/** Guarda el texto del análisis de un mes (lo edita o lo crea). */
export function useSaveInsight() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ month, text }: { month: string; text: string }) =>
      request<Insight>(insightPath(month), { method: 'PUT', body: JSON.stringify({ text }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
  })
}

/** La instrucción fija de «Copiar para Claude» (no cambia mientras corre el servidor). */
export function useClaudeInstruction() {
  return useQuery({
    queryKey: queryKeys.claudeInstruction,
    queryFn: async () => (await request<{ texto: string }>('/api/dossier/instruccion')).texto,
    staleTime: Infinity,
  })
}

/** El dossier del mes (Markdown y huella) con las cuentas elegidas: se pide al abrir el diálogo y
 * no se vuelve a pedir mientras está abierto (lo copiado debe ser lo que se ve). */
export function useDossier(month: string, selection: Selection) {
  return useQuery({
    queryKey: queryKeys.dossier(month, selection),
    queryFn: async (): Promise<Dossier> => {
      const { text, headers } = await requestText(dossierPath(month, selection))
      return { markdown: text, huella: hashFrom(headers) }
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
  /** La del dossier que se copió (null: la de hoy). */
  huella: string | null
}

/** Guarda la respuesta pegada de Claude como el análisis nuevo del mes (reemplaza al guardado). */
export function useSavePastedInsight() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ month, text, selection, huella }: PastedSave) =>
      request<Insight>(insightPath(month), {
        method: 'PUT',
        body: JSON.stringify(pastedBody(text, selection, huella)),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
  })
}

/** Borra el análisis de un mes. */
export function useDeleteInsight() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (month: string) => request<void>(insightPath(month), { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.insightsAll }),
  })
}

const CASH_BOX_KEY = [...queryKeys.transactions, 'caja-fuerte'] as const

/** La caja fuerte: saldo por moneda y sus movimientos. Va bajo `transactions`: cada cambio de un
 * vínculo, una corrección o una tasa la vuelve a pedir. */
export function useCashBox() {
  return useQuery({
    queryKey: CASH_BOX_KEY,
    queryFn: () => request<CashBox>('/api/cash-box'),
  })
}

export type CashBoxChange =
  | { action: 'add'; body: CashEntryBody }
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
    case 'update':
      return request<CashBox>(`/api/cash-box/entries/${change.id}`, json('PUT', change.body))
    case 'delete':
      return request<CashBox>(`/api/cash-box/entries/${change.id}`, { method: 'DELETE' })
    case 'store':
      return request<Tx>(`/api/cash-box/stored/${fp(change.fingerprint)}`, { method: 'PUT' })
    case 'unstore':
      // Sin cuerpo (204) si el retiro ya no aparece.
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

/** Anota, edita o borra un movimiento de la caja, o marca un retiro guardado o un depósito: todo
 * lo que muestra montos o categorías cambia, y la lista de cuentas (la caja aparece al usarla). */
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
