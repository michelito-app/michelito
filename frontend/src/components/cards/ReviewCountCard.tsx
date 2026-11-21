import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import { reviewHref } from '@/lib/home'
import { cashReviewCount, occurrenceQuestion } from '@/lib/cashBox'
import { useCashBox, useReview } from '@/lib/queries'
import { KIND_LABELS, mainAmountText } from '@/lib/review'
import { cn } from '@/lib/utils'
import { Card, FIGURE } from './Card'
import { CardError } from './CardError'

interface ReviewCountCardProps {
  month: string
  selection: Selection
}

/** «To review»: how many and the first one, on one line; the actions live in the review list,
 * where the card leads. */
export function ReviewCountCard({ month, selection }: ReviewCountCardProps) {
  const review = useReview(month, selection)
  const cash = useCashBox()
  const items = review.data ?? []
  const first = items[0]
  // The cash account's items count too (its occurrences and the monthly reconcile).
  const cashCount = cashReviewCount(cash.data)
  const cashFirst = cash.data?.occurrences[0]
  const total = items.length + cashCount
  return (
    <Card id="review" title={t('home.review.title')} href={reviewHref(month, selection)}>
      {review.isPending || cash.isPending ? (
        <Skeleton className="h-11 rounded-xl" />
      ) : review.isError ? (
        <CardError what={t('home.what.review')} error={review.error} onRetry={() => review.refetch()} />
      ) : total === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('home.review.none')} ✓</p>
      ) : (
        <>
          <p className={cn(FIGURE, 'text-[24px] leading-none')} data-testid="review-count">
            {t('home.review.count', { count: total })}
          </p>
          {!first && cashFirst && (
            <p className="min-w-0 truncate text-[13px] text-ink-2">{occurrenceQuestion(cashFirst)}</p>
          )}
          {first && (
            <p className="flex min-w-0 items-baseline gap-2 text-[13px] text-ink-2">
              <span className="shrink-0 font-semibold">{KIND_LABELS[first.kind]}</span>
              <span className="min-w-0 truncate">{first.merchant}</span>
              <span className="shrink-0 tabular-nums">{mainAmountText(first)}</span>
            </p>
          )}
        </>
      )}
    </Card>
  )
}
