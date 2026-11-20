import { ArrowLeft } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { t } from '@/i18n'
import { LoadError } from '@/components/LoadError'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { ExchangeSection } from '@/components/transactions/ExchangeSection'
import { InvestmentSection } from '@/components/transactions/InvestmentSection'
import { SharedTxPanel } from '@/components/shared/TxShared'
import { SECTION, SECTION_TITLE } from '@/components/transactions/linkParts'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { backPath, listPath, showExchange, showInvestment } from '@/lib/links'
import { useTransaction } from '@/lib/queries'
import {
  AMOUNT_TONE_CLASS,
  amountLines,
  amountTone,
  dayLabel,
  originText,
} from '@/lib/transactions'
import { cn } from '@/lib/utils'

const BACK =
  'inline-flex h-11 items-center gap-1.5 self-start rounded-xl px-2 -ml-2 text-sm font-semibold text-ink-2 hover:bg-muted hover:text-foreground'

/** A transaction's links screen (`/transactions/<fingerprint>`): the transaction on top and
 * the state of the shared expense, the reimbursement or the exchange; each with its picker
 * (search and "see more"). "Back" returns to the list it came from, with the row selected. */
export function LinkPage() {
  const { fingerprint = '' } = useParams()
  const location = useLocation()
  const from: unknown = (location.state as { from?: unknown } | null)?.from
  const query = useTransaction(fingerprint)

  if (query.isPending) return <PageSkeleton />
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404
    return (
      <div className="flex flex-col gap-4">
        <Link to={listPath(from)} className={cn(BACK, FOCUS)}>
          <ArrowLeft size={16} aria-hidden="true" />
          {t('links.page.back')}
        </Link>
        {missing ? (
          <div className={cn(PANEL, 'flex flex-col gap-2 px-6 py-10 text-center text-sm')}>
            <PageTitle className="text-xl font-bold">{t('links.page.notFound')}</PageTitle>
            {t('links.page.gone')}
          </div>
        ) : (
          <LoadError
            what={t('links.what.transaction')}
            error={query.error}
            onRetry={() => query.refetch()}
          />
        )}
      </div>
    )
  }

  const tx = query.data
  const amount = amountLines(tx)
  const anything = tx.ledger !== null || showExchange(tx) || showInvestment(tx)

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <Link to={backPath(tx, from)} className={cn(BACK, FOCUS)}>
        <ArrowLeft size={16} aria-hidden="true" />
        {t('links.page.back')}
      </Link>

      <header className={cn(PANEL, 'flex flex-col gap-1.5 px-5 py-4 sm:px-6')}>
        <span className="text-[13px] text-muted-foreground">
          {dayLabel(tx.day)} · {tx.account_label}
        </span>
        <PageTitle
          key={tx.fingerprint}
          className="text-[24px] leading-tight font-bold tracking-[-0.01em] break-words"
        >
          {tx.merchant}
        </PageTitle>
        <span
          className={cn(
            'text-[26px] leading-tight font-bold tabular-nums',
            AMOUNT_TONE_CLASS[amountTone(tx)],
          )}
        >
          {amount.main}
        </span>
        <span className="text-[13px] text-muted-foreground">{originText(tx)}</span>
        <span className="font-mono text-[12.5px] break-all text-ink-2">{tx.description}</span>
      </header>

      <div className="flex min-w-0 flex-col gap-5 [&>section]:bg-card [&>section]:p-4 sm:[&>section]:p-5">
        {tx.ledger !== null && (
          <section aria-label={t('shared.tx.title')} className={SECTION}>
            <h2 className={SECTION_TITLE}>{t('shared.tx.title')}</h2>
            <SharedTxPanel tx={tx} />
          </section>
        )}
        {showExchange(tx) && <ExchangeSection tx={tx} />}
        {showInvestment(tx) && <InvestmentSection tx={tx} />}
        {!anything && (
          <p className="text-sm text-muted-foreground">
            {t('links.page.nothing')}
          </p>
        )}
      </div>
    </div>
  )
}

/** The screen's h1: it takes focus on arrival, so a screen reader announces the route change. */
function PageTitle({ className, children }: { className: string; children: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [])
  return (
    <h1 ref={heading} tabIndex={-1} className={cn(className, 'outline-none')}>
      {children}
    </h1>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label={t('links.page.loading')} className="flex flex-col gap-5">
      <Skeleton className="h-11 w-24 rounded-xl" />
      <Skeleton className="h-36 rounded-2xl" />
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  )
}
