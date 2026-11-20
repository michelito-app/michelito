import { Link } from 'react-router'
import { FOCUS, ROW_DIVIDER } from '@/components/summary/styles'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { InvestmentRole, ReviewItem } from '@/lib/api'
import { useLinkToReserve } from '@/lib/budgetQueries'
import { useChangeInvestment, useDecideProvisional, useEditTransaction } from '@/lib/queries'
import { confirmPossiblePayment, useLedgerWrite } from '@/lib/sharedQueries'
import { amountText, itemHref, KIND_LABELS, metaText, openLabel, reviewedLabel } from '@/lib/review'
import { cn } from '@/lib/utils'

const ACTION = 'h-11 flex-[1_1_120px] rounded-xl text-sm font-semibold'
const SECONDARY = cn(ACTION, 'border-[#D6D6D0] bg-card text-ink-2')

interface ReviewRowProps {
  item: ReviewItem
  selection: Selection
  busy: boolean
  /** Marks or unmarks the movement as reviewed. */
  onReviewed: (item: ReviewItem, reviewed: boolean) => void
  /** Only for one-off expenses: "It is one-off" (marks it as a one-off expense). */
  onOneOff?: (item: ReviewItem) => void
}

/** A movement to review: kind, link to Transactions, why and what to do. One already reviewed
 * (in the history) offers to review it again. */
export function ReviewRow({ item, selection, busy, onReviewed, onOneOff }: ReviewRowProps) {
  return (
    <li className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge className="border border-up/30 bg-up-soft text-up-ink">{KIND_LABELS[item.kind]}</Badge>
        {item.reviewed && (
          <Badge className="bg-muted text-muted-foreground">{t('review.row.reviewed')}</Badge>
        )}
      </div>
      {/* Name, amount and account open the movement in Transactions; the buttons do not. */}
      <Link
        to={itemHref(item, selection)}
        aria-label={openLabel(item)}
        className={cn(
          '-mx-2 flex min-w-0 flex-col gap-0.5 rounded-md px-2 py-1 text-foreground no-underline transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={item.description}>
            {item.merchant}
          </span>
          <span aria-hidden="true" className="shrink-0 text-sm text-muted-foreground">
            →
          </span>
        </span>
        <span className="text-sm font-semibold whitespace-nowrap tabular-nums">{amountText(item)}</span>
        <span className="truncate text-[13px] text-muted-foreground" title={item.account_label}>
          {metaText(item)}
        </span>
      </Link>
      <p className="text-[13px] text-ink-2">{item.reason}</p>
      <div className="flex flex-wrap gap-2">
        {item.reviewed ? (
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={t('review.row.reviewAgainLabel', { merchant: item.merchant })}
            disabled={busy}
            onClick={() => onReviewed(item, false)}
          >
            {t('review.row.reviewAgain')}
          </Button>
        ) : item.investment_id != null &&
          (item.kind === 'possible_contribution' || item.kind === 'possible_return') ? (
          <InvestmentActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'possible_payment' && item.group_id != null ? (
          <PaymentActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'unconfirmed' || (item.kind === 'reversal' && item.provisional) ? (
          <UnconfirmedActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'possible_reserve' && item.reserve_id != null ? (
          <ReserveActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'possible_rule' && item.category_id != null ? (
          <RuleActions item={item} busy={busy} onReviewed={onReviewed} />
        ) : item.kind === 'one_off' ? (
          <>
            <Button
              className={ACTION}
              aria-label={t('review.row.oneOffLabel', { merchant: item.merchant })}
              disabled={busy || !onOneOff}
              onClick={() => onOneOff?.(item)}
            >
              {t('review.row.oneOff')}
            </Button>
            <Button
              variant="outline"
              className={SECONDARY}
              aria-label={reviewedLabel(item)}
              disabled={busy}
              onClick={() => onReviewed(item, true)}
            >
              {t('review.row.notOneOff')}
            </Button>
          </>
        ) : (
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={reviewedLabel(item)}
            disabled={busy}
            onClick={() => onReviewed(item, true)}
          >
            {item.kind === 'possible_rule' ? t('review.row.dismiss') : t('review.row.done')}
          </Button>
        )}
      </div>
    </li>
  )
}

interface InvestmentActionsProps {
  item: ReviewItem
  busy: boolean
  onReviewed: (item: ReviewItem, reviewed: boolean) => void
}

/** A possible contribution or return: confirming it is one tap (it links it to the proposed
 * investment); "It is not" marks it reviewed. A mixed return is set from its screen. */
function InvestmentActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const change = useChangeInvestment()
  const link = (role: InvestmentRole) =>
    change.mutate({
      action: 'add',
      id: item.investment_id!,
      fingerprint: item.fingerprint,
      role,
    })
  const pending = busy || change.isPending
  return (
    <>
      {item.kind === 'possible_contribution' ? (
        <Button
          className={ACTION}
          aria-label={t('review.row.contributionLabel', { merchant: item.merchant })}
          disabled={pending}
          onClick={() => link('contribution')}
        >
          {t('review.row.contribution')}
        </Button>
      ) : (
        <>
          <Button
            className={ACTION}
            aria-label={t('review.row.returnLabel', { merchant: item.merchant })}
            disabled={pending}
            onClick={() => link('return')}
          >
            {t('review.row.return')}
          </Button>
          <Button
            variant="outline"
            className={SECONDARY}
            aria-label={t('review.row.capitalLabel', { merchant: item.merchant })}
            disabled={pending}
            onClick={() => link('capital')}
          >
            {t('review.row.capital')}
          </Button>
        </>
      )}
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={t('review.row.notInvestmentLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        {t('review.row.notInvestment')}
      </Button>
      {change.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('review.row.saveError', { message: change.error.message })}
        </p>
      )}
    </>
  )
}

/** A possible rule: "Always" creates the merchant rule with the proposed category (it is
 * recorded in the log); "Dismiss" does not propose it again. */
function RuleActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const edit = useEditTransaction()
  const pending = busy || edit.isPending
  return (
    <>
      <Button
        className={ACTION}
        aria-label={t('review.row.ruleLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() =>
          edit.mutate({
            fingerprint: item.fingerprint,
            body: { category_id: item.category_id!, scope: 'merchant' },
          })
        }
      >
        {t('review.row.rule')}
      </Button>
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={reviewedLabel(item)}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        {t('review.row.dismiss')}
      </Button>
      {edit.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('review.row.saveError', { message: edit.error.message })}
        </p>
      )}
    </>
  )
}

/** A provisional (from a bank alert) missing from its statement: "Discard" removes it (it was
 * reversed or never charged; undoable from the log); "Keep" leaves it counted and reviewed. */
function UnconfirmedActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const decide = useDecideProvisional()
  const pending = busy || decide.isPending
  return (
    <>
      <Button
        className={ACTION}
        aria-label={t('review.row.discardLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => decide.mutate({ fingerprint: item.fingerprint, decision: 'discard' })}
      >
        {t('review.row.discard')}
      </Button>
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={t('review.row.keepLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        {t('review.row.keep')}
      </Button>
      {decide.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('review.row.saveError', { message: decide.error.message })}
        </p>
      )}
    </>
  )
}

/** An expense that looks like it belongs to a reserve: "Yes, it is from the reserve" links it
 * (it leaves its category's cap); "No" marks it reviewed and it does not come back. */
function ReserveActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const link = useLinkToReserve()
  const pending = busy || link.isPending
  return (
    <>
      <Button
        className={ACTION}
        aria-label={t('review.row.reserveLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => link.mutate({ id: item.reserve_id!, fingerprints: [item.fingerprint] })}
      >
        {t('review.row.reserve')}
      </Button>
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={t('review.row.notReserveLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        {t('review.row.notReserve')}
      </Button>
      {link.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('review.row.saveError', { message: link.error.message })}
        </p>
      )}
    </>
  )
}

/** "Did Ana pay you?": yes records the payment with this credit and links it (one tap); "No"
 * marks it reviewed. */
function PaymentActions({ item, busy, onReviewed }: InvestmentActionsProps) {
  const pay = useLedgerWrite()
  const pending = busy || pay.isPending
  return (
    <>
      <Button
        className={ACTION}
        aria-label={t('review.row.paymentLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => pay.mutate(() => confirmPossiblePayment(item))}
      >
        {t('review.row.payment')}
      </Button>
      <Button
        variant="outline"
        className={SECONDARY}
        aria-label={t('review.row.notPaymentLabel', { merchant: item.merchant })}
        disabled={pending}
        onClick={() => onReviewed(item, true)}
      >
        {t('review.row.notPayment')}
      </Button>
      {pay.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('review.row.saveError', { message: pay.error.message })}
        </p>
      )}
    </>
  )
}
