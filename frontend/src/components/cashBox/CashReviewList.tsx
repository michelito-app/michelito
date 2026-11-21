import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { ROW_DIVIDER } from '@/components/summary/styles'
import { Action, FIELD, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { CashBox, CashOccurrence } from '@/lib/api'
import { cashReviewCount, occurrenceMeta, occurrenceQuestion } from '@/lib/cashBox'
import { parseCents } from '@/lib/links'
import { useChangeCashBox } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { ReconcileForm } from './ReconcileForm'

/** The cash part of "To review": each scheduled occurrence with its answers, and the monthly
 * "how much cash do you have?". */
export function CashReviewList({ box }: { box: CashBox }) {
  const [reconciling, setReconciling] = useState(false)
  if (cashReviewCount(box) === 0) return null
  return (
    <ul aria-label={t('cashBox.review.listLabel')} className="flex flex-col">
      {box.occurrences.map((item) => (
        <OccurrenceRow key={item.entry_id} item={item} />
      ))}
      {box.reconcile_due && (
        <li className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-2')}>
          <div className="flex items-center gap-2">
            <Badge className="border border-up/30 bg-up-soft text-up-ink">
              {t('cashBox.title')}
            </Badge>
            <span className="min-w-0 flex-1 text-sm font-semibold">
              {t('cashBox.reconcile.prompt')}
            </span>
          </div>
          {reconciling ? (
            <ReconcileForm box={box} onDone={() => setReconciling(false)} />
          ) : (
            <div>
              <Action primary onClick={() => setReconciling(true)}>
                {t('cashBox.reconcile.open')}
              </Action>
            </div>
          )}
        </li>
      )}
    </ul>
  )
}

function OccurrenceRow({ item }: { item: CashOccurrence }) {
  const change = useChangeCashBox()
  const [other, setOther] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const paying = item.kind === 'expense'

  function answer(action: 'confirm' | 'skip') {
    change.mutate({ action: 'answer', id: item.entry_id, answer: action })
  }

  function saveAmount() {
    const cents = parseCents(other ?? '')
    if (cents === null) {
      setError(t('cashBox.error.amount'))
      return
    }
    change.mutate({ action: 'answer', id: item.entry_id, answer: 'amount', amount_cents: cents })
  }

  return (
    <li data-testid="cash-occurrence" className={cn(ROW_DIVIDER, 'flex flex-col gap-1.5 py-2')}>
      <div className="flex items-center gap-2">
        <Badge className="border border-up/30 bg-up-soft text-up-ink">{t('cashBox.title')}</Badge>
        <span className="min-w-0 flex-1 text-sm font-semibold break-words">
          {occurrenceQuestion(item)}
        </span>
      </div>
      <span className="text-[13px] text-ink-2">{occurrenceMeta(item)}</span>
      {item.state === 'lapsed' && (
        <span className="text-[13px] text-muted-foreground">{t('cashBox.review.lapsed')}</span>
      )}
      {other === null ? (
        <div className="flex flex-wrap gap-1.5">
          <Action primary disabled={change.isPending} onClick={() => answer('confirm')}>
            {paying ? t('cashBox.review.paid') : t('cashBox.review.received')}
          </Action>
          <Action
            disabled={change.isPending}
            onClick={() => setOther((item.amount_cents / 100).toFixed(2))}
          >
            {paying ? t('cashBox.review.otherPaid') : t('cashBox.review.otherReceived')}
          </Action>
          <Action disabled={change.isPending} onClick={() => answer('skip')}>
            {paying ? t('cashBox.review.notPaid') : t('cashBox.review.notReceived')}
          </Action>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
            {t('cashBox.review.amountLabel', { concept: item.concept })}
            <input
              className={FIELD}
              inputMode="decimal"
              autoComplete="off"
              value={other}
              onChange={(event) => {
                setOther(event.target.value)
                setError(null)
              }}
            />
          </label>
          <Action primary disabled={change.isPending} onClick={saveAmount}>
            {t('cashBox.review.saveAmount')}
          </Action>
          <Action onClick={() => setOther(null)}>{t('cashBox.form.cancel')}</Action>
        </div>
      )}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {error}
        </p>
      )}
      <Failure error={change.error} />
    </li>
  )
}
