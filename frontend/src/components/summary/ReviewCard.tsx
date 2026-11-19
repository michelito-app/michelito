import { useId, useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import type { Selection } from '@/lib/accountFilter'
import type { InvestmentRole, ReviewItem } from '@/lib/api'
import {
  useChangeInvestment,
  useEditTransaction,
  useMarkReviewed,
  useReview,
} from '@/lib/queries'
import {
  cardTitle,
  itemHref,
  itemKey,
  KIND_LABELS,
  mainAmountText,
  metaText,
  openLabel,
  originalAmountText,
} from '@/lib/review'
import { REVIEW_LIMIT, splitTop } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from './styles'

const NONE: ReadonlySet<string> = new Set()

/** Small button with a 44 px tall touch area (without moving what is next to it). */
const ACTION = cn(
  'relative inline-flex h-8 min-w-11 items-center justify-center rounded-lg border px-3 text-[13px] font-semibold whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50',
  'before:absolute before:-inset-y-1.5 before:inset-x-0 before:content-[""]',
  FOCUS,
)
const PRIMARY = cn(ACTION, 'border-transparent bg-primary text-primary-foreground hover:bg-primary/85')
const SECONDARY = cn(ACTION, 'border-[#D6D6D0] bg-card text-ink-2 hover:bg-muted')

interface ReviewCardProps {
  month: string
  selection?: Selection
}

/** "To review": what is worth a look in the month (possible one-off expenses, unusual income,
 * large transfers, possible duplicate charges and price rises), each notice on two lines with its
 * actions. The first ones show and "See all" expands the rest. What was reviewed leaves the card;
 * the history lives in Reports. */
export function ReviewCard({ month, selection = null }: ReviewCardProps) {
  const review = useReview(month, selection)
  const edit = useEditTransaction()
  const mark = useMarkReviewed()
  const invest = useChangeInvestment()
  const [all, setAll] = useState(false)
  // What was decided leaves the card at once; when new data arrives the server rules.
  const updatedAt = review.dataUpdatedAt
  const [decided, setDecided] = useState<{ at: number; keys: ReadonlySet<string> }>({
    at: updatedAt,
    keys: new Set(),
  })
  const hidden = decided.at === updatedAt ? decided.keys : NONE

  if (review.isPending) return <Skeleton className="h-full min-h-[180px] rounded-2xl" />

  const items = (review.data ?? []).filter((item) => !hidden.has(itemKey(item)))
  const { shown, rest } = splitTop(items, REVIEW_LIMIT, all)

  function hide(item: ReviewItem) {
    setDecided((current) => ({
      at: updatedAt,
      keys: new Set([...(current.at === updatedAt ? current.keys : NONE), itemKey(item)]),
    }))
  }

  function confirmOneOff(item: ReviewItem) {
    edit.mutate(
      { fingerprint: item.fingerprint, body: { one_off: true, scope: 'transaction' } },
      { onSuccess: () => hide(item) },
    )
  }

  /** A possible contribution or return: links it to the proposed investment. */
  function confirmInvestment(item: ReviewItem, role: InvestmentRole) {
    if (item.investment_id == null) return
    invest.mutate(
      { action: 'add', id: item.investment_id, fingerprint: item.fingerprint, role },
      { onSuccess: () => hide(item) },
    )
  }

  /** A possible rule: "Always" creates the merchant's rule with that category. */
  function acceptRule(item: ReviewItem) {
    if (item.category_id == null) return
    edit.mutate(
      {
        fingerprint: item.fingerprint,
        body: { category_id: item.category_id, scope: 'merchant' },
      },
      { onSuccess: () => hide(item) },
    )
  }

  function reviewed(item: ReviewItem) {
    mark.mutate(
      { kind: item.kind, fingerprint: item.fingerprint, reviewed: true },
      { onSuccess: () => hide(item) },
    )
  }

  if (items.length === 0) {
    return (
      <section
        aria-labelledby="review-title"
        className={cn(PANEL, 'flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-3.5 sm:px-6')}
      >
        <h2 id="review-title" className="text-[15px] font-[650] tracking-tight">
          {t('summary.review.title')}
        </h2>
        <p className="text-[13px] text-muted-foreground">
          {review.isError
            ? t('summary.review.loadError', { message: review.error.message })
            : t('summary.review.empty')}
        </p>
      </section>
    )
  }

  const error = edit.error ?? mark.error ?? invest.error
  const busy = edit.isPending || mark.isPending || invest.isPending
  return (
    <section
      aria-labelledby="review-title"
      className={cn(PANEL, 'flex h-full min-w-0 flex-col gap-2 px-4 py-5 sm:px-6')}
    >
      <div className="flex flex-col gap-1">
        <h2 id="review-title" className={PANEL_TITLE}>
          {cardTitle(items.length)}
        </h2>
        <p className="text-[13px] text-muted-foreground">
          {t('summary.review.oneOffHint')}
        </p>
      </div>
      <ul className="flex flex-col">
        {shown.map((item) => (
          <ReviewLine
            key={itemKey(item)}
            item={item}
            selection={selection}
            busy={busy}
            onReviewed={reviewed}
            onOneOff={confirmOneOff}
            onInvest={confirmInvestment}
            onRule={acceptRule}
          />
        ))}
      </ul>
      {(all || rest.length > 0) && (
        <button
          type="button"
          aria-expanded={all}
          onClick={() => setAll((value) => !value)}
          className={cn(
            '-mx-2 flex min-h-11 items-center self-start rounded-md px-2 text-[13px] font-semibold text-primary hover:bg-muted/60',
            FOCUS,
          )}
        >
          {all ? t('summary.review.seeLess') : t('summary.review.seeAll', { count: items.length })}
        </button>
      )}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('summary.review.saveError', { message: error.message })}
        </p>
      )}
    </section>
  )
}

interface ReviewLineProps {
  item: ReviewItem
  selection: Selection
  busy: boolean
  onReviewed: (item: ReviewItem) => void
  onOneOff: (item: ReviewItem) => void
  onInvest: (item: ReviewItem, role: InvestmentRole) => void
  onRule: (item: ReviewItem) => void
}

/** A notice on two lines: kind, merchant and amount (they open the transaction in Transactions);
 * below, day, account and reason in grey, with the actions on the right. */
function ReviewLine({
  item,
  selection,
  busy,
  onReviewed,
  onOneOff,
  onInvest,
  onRule,
}: ReviewLineProps) {
  const reason = useId()
  const original = originalAmountText(item)
  const investing =
    item.investment_id != null &&
    (item.kind === 'possible_contribution' || item.kind === 'possible_return')
  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col gap-0.5 py-2')}>
      <Link
        to={itemHref(item, selection)}
        aria-label={openLabel(item)}
        aria-describedby={reason}
        className={cn(
          '-mx-2 flex min-h-11 min-w-0 items-center gap-2 rounded-md px-2 py-1 text-foreground no-underline transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        <Badge className="border border-up/30 bg-up-soft text-up-ink">{KIND_LABELS[item.kind]}</Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={item.description}>
          {item.merchant}
        </span>
        <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums">
          {mainAmountText(item)}
        </span>
      </Link>
      {/* With three buttons (a possible return), the row wraps instead of overflowing. */}
      <div
        className={cn('flex items-start gap-3', investing && 'flex-wrap gap-x-3 gap-y-1.5')}
      >
        <p
          id={reason}
          className={cn(
            'line-clamp-2 min-w-0 flex-1 text-[13px] text-muted-foreground',
            investing && 'basis-48',
          )}
        >
          <span title={item.account_label}>{metaText(item)}</span>
          {original && ` · ${original}`} · {item.reason}
        </p>
        <span className={cn('flex gap-1.5', investing ? 'flex-wrap' : 'shrink-0')}>
          {investing ? (
            <InvestmentButtons item={item} busy={busy} onReviewed={onReviewed} onInvest={onInvest} />
          ) : item.kind === 'possible_rule' ? (
            <>
              <button
                type="button"
                className={PRIMARY}
                aria-label={t('summary.review.createRuleLabel', { merchant: item.merchant })}
                disabled={busy}
                onClick={() => onRule(item)}
              >
                {t('summary.review.always')}
              </button>
              <button
                type="button"
                className={SECONDARY}
                aria-label={t('summary.review.dismissRuleLabel', { merchant: item.merchant })}
                disabled={busy}
                onClick={() => onReviewed(item)}
              >
                {t('summary.review.dismiss')}
              </button>
            </>
          ) : item.kind === 'one_off' ? (
            <>
              <button
                type="button"
                className={PRIMARY}
                aria-label={t('summary.oneOffs.confirmLabel', { merchant: item.merchant })}
                disabled={busy}
                onClick={() => onOneOff(item)}
              >
                {t('summary.review.oneOff')}
              </button>
              <button
                type="button"
                className={SECONDARY}
                aria-label={t('summary.oneOffs.dismissLabel', { merchant: item.merchant })}
                disabled={busy}
                onClick={() => onReviewed(item)}
              >
                {t('summary.review.no')}
              </button>
            </>
          ) : (
            <button
              type="button"
              className={SECONDARY}
              aria-label={t('summary.review.reviewedLabel', { merchant: item.merchant })}
              disabled={busy}
              onClick={() => onReviewed(item)}
            >
              {t('summary.review.reviewed')}
            </button>
          )}
        </span>
      </div>
    </li>
  )
}

type InvestmentButtonsProps = Pick<ReviewLineProps, 'item' | 'busy' | 'onReviewed' | 'onInvest'>

/** Another contribution? "Contribution" / A return? "Return" or "Capital" (a mixed one, from its
 * screen); "No" marks it reviewed. Proposing never links: confirming is this tap. */
function InvestmentButtons({ item, busy, onReviewed, onInvest }: InvestmentButtonsProps) {
  return (
    <>
      {item.kind === 'possible_contribution' ? (
        <button
          type="button"
          className={PRIMARY}
          aria-label={t('summary.review.contributionLabel', { merchant: item.merchant })}
          disabled={busy}
          onClick={() => onInvest(item, 'contribution')}
        >
          {t('summary.review.contribution')}
        </button>
      ) : (
        <>
          <button
            type="button"
            className={PRIMARY}
            aria-label={t('summary.review.returnLabel', { merchant: item.merchant })}
            disabled={busy}
            onClick={() => onInvest(item, 'return')}
          >
            {t('summary.review.return')}
          </button>
          <button
            type="button"
            className={SECONDARY}
            aria-label={t('summary.review.capitalLabel', { merchant: item.merchant })}
            disabled={busy}
            onClick={() => onInvest(item, 'capital')}
          >
            {t('summary.review.capital')}
          </button>
        </>
      )}
      <button
        type="button"
        className={SECONDARY}
        aria-label={t('summary.review.notInvestmentLabel', { merchant: item.merchant })}
        disabled={busy}
        onClick={() => onReviewed(item)}
      >
        {t('summary.review.no')}
      </button>
    </>
  )
}
