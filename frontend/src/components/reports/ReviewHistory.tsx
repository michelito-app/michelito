import { useState } from 'react'
import { LoadError } from '@/components/LoadError'
import { ReviewRow } from '@/components/review/ReviewRow'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import type { Selection } from '@/lib/accountFilter'
import type { ReviewItem, ReviewKind } from '@/lib/api'
import { useEditTransaction, useMarkReviewed, useReviewHistory } from '@/lib/queries'
import { itemKey, KIND_LABELS, REVIEW_KINDS } from '@/lib/review'
import { cn } from '@/lib/utils'

const CHIP = cn(
  'min-h-9 rounded-full border px-3 text-[13px] font-medium transition-colors',
  FOCUS,
)

/** Historial de «Para revisar» de los últimos 12 meses: pendiente y revisado, con filtro por
 * tipo. Lo revisado se puede volver a revisar. */
export function ReviewHistory({ selection }: { selection: Selection }) {
  const [kind, setKind] = useState<ReviewKind | null>(null)
  const history = useReviewHistory(selection, kind)
  const mark = useMarkReviewed()
  const edit = useEditTransaction()

  function reviewed(item: ReviewItem, value: boolean) {
    mark.mutate({ kind: item.kind, fingerprint: item.fingerprint, reviewed: value })
  }

  function confirmOneOff(item: ReviewItem) {
    edit.mutate({ fingerprint: item.fingerprint, body: { one_off: true, scope: 'transaction' } })
  }

  const items = history.data ?? []
  const pending = items.filter((i) => !i.reviewed).length
  const error = mark.error ?? edit.error
  return (
    <section aria-labelledby="history-title" className={cn(PANEL, 'flex min-w-0 flex-col gap-3 px-6 py-5')}>
      <div className="flex flex-col gap-1">
        <h2 id="history-title" className={PANEL_TITLE}>
          Para revisar: historial
        </h2>
        <p className="text-[13px] text-muted-foreground">
          Últimos 12 meses · {pending} pendientes de {items.length}
        </p>
      </div>
      <div role="group" aria-label="Filtrar por tipo" className="flex flex-wrap gap-2">
        {[null, ...REVIEW_KINDS].map((value) => {
          const active = value === kind
          return (
            <button
              key={value ?? 'todos'}
              type="button"
              aria-pressed={active}
              onClick={() => setKind(value)}
              className={cn(
                CHIP,
                active
                  ? 'border-primary bg-secondary text-secondary-foreground'
                  : 'border-border bg-card text-ink-2 hover:bg-muted',
              )}
            >
              {value === null ? 'Todos' : KIND_LABELS[value]}
            </button>
          )
        })}
      </div>
      {history.isError ? (
        <LoadError what="el historial" error={history.error} onRetry={() => history.refetch()} />
      ) : history.isPending ? (
        <Skeleton className="h-32 rounded-xl" />
      ) : items.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Nada para revisar en estos meses.</p>
      ) : (
        <ul aria-busy={history.isPlaceholderData} className="flex flex-col">
          {items.map((item) => (
            <ReviewRow
              key={itemKey(item)}
              item={item}
              selection={selection}
              busy={mark.isPending || edit.isPending}
              onReviewed={reviewed}
              onOneOff={confirmOneOff}
            />
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {error.message}
        </p>
      )}
    </section>
  )
}
