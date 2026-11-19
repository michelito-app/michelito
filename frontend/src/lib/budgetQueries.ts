// Consultas del presupuesto y las reservas. Cada escritura vuelve a pedir el presupuesto, las
// reservas, la tarjeta del Resumen, «Para revisar» y las transacciones (con ellas, la bitácora).
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
  return selectionParam(selection) ?? 'todas'
}

export const budgetKeys = {
  all: ['budget'] as const,
  month: (month: string, selection: Selection) =>
    ['budget', 'mes', month, scope(selection)] as const,
  overview: (month: string, selection: Selection) =>
    ['budget', 'resumen', month, scope(selection)] as const,
  reserves: (selection: Selection) => ['budget', 'reservas', scope(selection)] as const,
  tx: (fingerprint: string) => ['budget', 'tx', fingerprint] as const,
  options: ['budget', 'opciones'] as const,
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

/** Topes y gasto del mes por categoría (cuentas elegidas). */
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

/** La tarjeta del Resumen y la línea «después de apartar» de «Te quedó». */
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

/** Solo el id y el nombre de cada reserva (el selector de la selección múltiple). */
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

/** El tope a mano (null: «Sin presupuesto»). */
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

/** Aceptar o ignorar el aviso de «lo habitual cambió». */
export function useResolveWarning() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ categoryId, accept }: { categoryId: number; accept: boolean }) =>
      request<EntryResult>(`/api/budget/caps/${categoryId}/habitual`, {
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

/** Crear, editar o borrar una reserva, descartar una sugerencia o quitar un gasto. */
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

/** Vincula uno o varios gastos a una reserva (desde el detalle, «Para revisar» o la selección). */
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
