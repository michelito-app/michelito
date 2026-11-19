// Consultas de la bitácora. Las claves van bajo `transactions`: cada cambio que invalida las
// transacciones vuelve a pedir también la bitácora y el historial.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'
import { type LogEntry, type LogFilters, type LogPage, logPath, type TxHistory } from './log'

export const logKeys = {
  all: ['transactions', 'log'] as const,
  page: (filters: LogFilters, limit: number) =>
    ['transactions', 'log', filters.kind, filters.author, filters.q.trim(), limit] as const,
  history: (fingerprint: string) => ['transactions', 'history', fingerprint] as const,
}

/** Las entradas con los filtros; `limit` crece con «Ver más». */
export function useLog(filters: LogFilters, limit: number) {
  return useQuery({
    queryKey: logKeys.page(filters, limit),
    queryFn: () => request<LogPage>(logPath(filters, 0, limit)),
    placeholderData: keepPreviousData,
  })
}

/** Lo registrado de una transacción y la pista de la regla posible. */
export function useHistory(fingerprint: string) {
  return useQuery({
    queryKey: logKeys.history(fingerprint),
    queryFn: () =>
      request<TxHistory>(`/api/transactions/${encodeURIComponent(fingerprint)}/history`),
  })
}

/** El motivo de una entrada (no es un cambio: solo cambia la bitácora). */
export function useSaveReason() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<LogEntry>(`/api/log/${id}`, { method: 'PATCH', body: JSON.stringify({ reason }) }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: logKeys.all }),
        client.invalidateQueries({ queryKey: ['transactions', 'history'] }),
      ]),
  })
}

/** Deshace una entrada: puede cambiar cualquier cosa, así que se vuelve a pedir todo. */
export function useUndo() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => request<LogEntry>(`/api/log/${id}/undo`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries(),
  })
}
