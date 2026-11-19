import { useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'
import { membersResultText } from '@/lib/budget'
import { useLinkToReserve, useReserveOptions } from '@/lib/budgetQueries'
import type { BatchNote } from '@/lib/useTxSelection'
import { cn } from '@/lib/utils'

const CONTROL = cn(
  'h-11 min-w-0 rounded-xl border border-border bg-card px-3 text-sm text-foreground',
  FOCUS,
)
const ACTION = cn('h-11 shrink-0 rounded-xl px-4 text-sm font-semibold', FOCUS)

interface ReserveBatchProps {
  chosen: Tx[]
  onDone: (note: BatchNote) => void
}

/** In the selection bar: link several expenses to a reserve at once (rows that are not expenses
 * or are already in a link are skipped, and the result says how many). Only when there are
 * reserves. */
export function ReserveBatch({ chosen, onDone }: ReserveBatchProps) {
  const reserves = useReserveOptions()
  const [reserveId, setReserveId] = useState('')
  const link = useLinkToReserve()
  const items = reserves.data ?? []
  if (items.length === 0) return null
  const target = items.find((r) => String(r.id) === reserveId) ?? null

  function apply() {
    if (!target || chosen.length === 0) return
    link.mutate(
      { id: target.id, fingerprints: chosen.map((t) => t.fingerprint) },
      {
        onSuccess: (result) =>
          onDone({ text: membersResultText(result, target.name), entryId: result.entry_id }),
      },
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        aria-label={t('transactions.reserveBatch.label')}
        value={reserveId}
        onChange={(event) => setReserveId(event.target.value)}
        className={cn(CONTROL, 'flex-[1_1_200px] font-semibold')}
      >
        <option value="">{t('transactions.reserveBatch.placeholder')}</option>
        {items.map((reserve) => (
          <option key={reserve.id} value={String(reserve.id)}>
            {reserve.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={apply}
        disabled={!target || chosen.length === 0 || link.isPending}
        className={cn(
          ACTION,
          'border border-border bg-card text-foreground hover:bg-muted disabled:opacity-50',
        )}
      >
        {link.isPending ? t('transactions.reserveBatch.linking') : t('transactions.reserveBatch.link')}
      </button>
      {link.isError && (
        <p role="alert" className="basis-full text-[13px] font-semibold text-up">
          {t('transactions.reserveBatch.error', { message: link.error.message })}
        </p>
      )}
    </div>
  )
}
