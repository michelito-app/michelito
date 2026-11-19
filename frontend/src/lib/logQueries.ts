// Change-log queries. The keys live under `transactions`: every change that invalidates the
// transactions also refetches the log and the history.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'
import { type LogEntry, type LogFilters, type LogPage, logPath, type TxHistory } from './log'

export const logKeys = {
  all: ['transactions', 'log'] as const,
  page: (filters: LogFilters, limit: number) =>
    ['transactions', 'log', filters.kind, filters.author, filters.q.trim(), limit] as const,
  history: (fingerprint: string) => ['transactions', 'history', fingerprint] as const,
}

/** The entries with the filters; `limit` grows with "See more". */
export function useLog(filters: LogFilters, limit: number) {
  return useQuery({
    queryKey: logKeys.page(filters, limit),
    queryFn: () => request<LogPage>(logPath(filters, 0, limit)),
    placeholderData: keepPreviousData,
  })
}

/** What was recorded for a transaction and the hint of a possible rule. */
export function useHistory(fingerprint: string) {
  return useQuery({
    queryKey: logKeys.history(fingerprint),
    queryFn: () =>
      request<TxHistory>(`/api/transactions/${encodeURIComponent(fingerprint)}/history`),
  })
}

/** The reason of an entry (not a change: only the log changes). */
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

/** Undoes an entry: it may change anything, so everything is refetched. */
export function useUndo() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => request<LogEntry>(`/api/log/${id}/undo`, { method: 'POST' }),
    onSuccess: () => client.invalidateQueries(),
  })
}
