// Tags: the list, one tag, the candidates to add, and the writes. A write changes the rows'
// chips and the change log: they are invalidated with the tags.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'
import { logKeys } from './logQueries'
import { queryKeys } from './queries'
import type { CandidateFilters, Tag, TagCandidates, TagSummary } from './tags'

export const tagKeys = {
  all: ['tags'] as const,
  one: (id: number) => ['tags', id] as const,
  candidates: (id: number, filters: CandidateFilters) => ['tags', id, 'candidates', filters] as const,
}

function tagPath(id: number): string {
  return `/api/tags/${id}`
}

function query(filters: CandidateFilters): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  const text = params.toString()
  return text === '' ? '' : `?${text}`
}

export function useTags(enabled = true) {
  return useQuery({ enabled, queryKey: tagKeys.all, queryFn: () => request<TagSummary[]>('/api/tags') })
}

export function useTag(id: number, enabled = true) {
  return useQuery({ enabled, queryKey: tagKeys.one(id), queryFn: () => request<Tag>(tagPath(id)) })
}

export function useTagCandidates(id: number, filters: CandidateFilters, enabled = true) {
  return useQuery({
    enabled,
    queryKey: tagKeys.candidates(id, filters),
    queryFn: () => request<TagCandidates>(`${tagPath(id)}/candidates${query(filters)}`),
  })
}

function useInvalidateTags() {
  const client = useQueryClient()
  return () =>
    Promise.all(
      [tagKeys.all, queryKeys.transactions, logKeys.all, queryKeys.summaries, queryKeys.oneOffsAll].map(
        (queryKey) => client.invalidateQueries({ queryKey }),
      ),
    )
}

function useTagWrite<T, R>(call: (input: T) => Promise<R>) {
  const invalidate = useInvalidateTags()
  return useMutation({ mutationFn: call, onSuccess: invalidate })
}

export function useCreateTag() {
  return useTagWrite((name: string) =>
    request<TagSummary>('/api/tags', { method: 'POST', body: JSON.stringify({ name }) }),
  )
}

export function useRenameTag() {
  return useTagWrite(({ id, name }: { id: number; name: string }) =>
    request<Tag>(tagPath(id), { method: 'PATCH', body: JSON.stringify({ name }) }),
  )
}

export function useDeleteTag() {
  return useTagWrite((id: number) => request<void>(tagPath(id), { method: 'DELETE' }))
}

/** Tag many transactions at once: one log entry. */
export function useTagTransactions() {
  return useTagWrite(({ id, fingerprints }: { id: number; fingerprints: string[] }) =>
    request<{ added: number; entry_id: number | null }>(`${tagPath(id)}/transactions`, {
      method: 'POST',
      body: JSON.stringify({ fingerprints }),
    }),
  )
}

export function useUntagTransactions() {
  return useTagWrite(({ id, fingerprints }: { id: number; fingerprints: string[] }) =>
    request<{ removed: number; entry_id: number | null }>(`${tagPath(id)}/transactions`, {
      method: 'DELETE',
      body: JSON.stringify({ fingerprints }),
    }),
  )
}

/** Tag (or untag) a whole loan or installment plan. */
export function useTagTarget() {
  return useTagWrite(
    ({ id, kind, targetId, on }: { id: number; kind: 'loans' | 'installments'; targetId: number; on: boolean }) =>
      request<Tag>(`${tagPath(id)}/${kind}/${targetId}`, { method: on ? 'PUT' : 'DELETE' }),
  )
}

/** "Mark all as one-off": every counted transaction of the tag, in one log entry. */
export function useTagOneOff() {
  return useTagWrite(({ id, oneOff }: { id: number; oneOff: boolean }) =>
    request<{ changed: number; entry_id: number | null }>(`${tagPath(id)}/one-off`, {
      method: 'POST',
      body: JSON.stringify({ one_off: oneOff }),
    }),
  )
}
