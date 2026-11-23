import { ChevronRight } from 'lucide-react'
import { useId } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import { balanceText, loanAccountKey, progress, rateText, remainingLine } from '@/lib/loans'
import { cn } from '@/lib/utils'

/** A loan in «Deudas»: what is owed, how much is paid off and when it ends; it opens the
 * loan's card in Accounts. */
export function LoanSummaryCard({ loan }: { loan: Loan }) {
  const titleId = useId()
  const share = progress(loan)
  return (
    <article
      data-testid="loan-summary"
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded-xl border border-border bg-card px-4 py-3.5"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 id={titleId} className="text-[15px] font-bold break-words">
            {loan.name}
          </h3>
          <span className="text-[13px] text-muted-foreground tabular-nums">
            {t('loans.card.rate', { rate: rateText(loan.rate_bp) })} ·{' '}
            {t('loans.card.of', { amount: formatMoney(loan.principal_cents, loan.currency) })}
          </span>
        </div>
        <span className="text-base font-bold whitespace-nowrap tabular-nums">{balanceText(loan)}</span>
      </header>
      <div aria-hidden="true" className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full origin-left rounded-full bg-primary transition-transform duration-300"
          style={{ transform: `scaleX(${share})` }}
        />
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-semibold tabular-nums">{remainingLine(loan)}</span>
        <Link
          to={`/accounts?account=${loanAccountKey(loan.id)}`}
          aria-label={t('loans.list.openLabel', { name: loan.name })}
          className={cn(
            '-mx-1 inline-flex min-h-11 items-center gap-1 rounded-[10px] px-1 text-[13px] font-semibold text-primary no-underline hover:bg-muted',
            FOCUS,
          )}
        >
          {t('loans.list.open')}
          <ChevronRight size={15} aria-hidden="true" />
        </Link>
      </footer>
    </article>
  )
}
