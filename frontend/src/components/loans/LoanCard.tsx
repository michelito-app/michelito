import { ChevronDown, Pencil, TriangleAlert } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { BalanceChart } from '@/components/accounts/BalanceChart'
import { PANEL } from '@/components/summary/styles'
import { Action } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import {
  balanceText,
  differenceText,
  interestLine,
  paidLine,
  progress,
  rateText,
  remainingLine,
} from '@/lib/loans'
import { longDay } from '@/lib/months'
import { cn } from '@/lib/utils'
import { LoanBalances } from './LoanBalances'
import { LoanEstimates } from './LoanEstimates'
import { LoanInstallments } from './LoanInstallments'
import { LoanFormSheet } from './LoanFormSheet'
import { LoanPayments } from './LoanPayments'
import { LoanRates } from './LoanRates'
import { LoanSchedule } from './LoanSchedule'

/** A loan's card in Accounts: the balance (negative, like a card's), what was paid and the
 * interest in it, what is left and when it ends; its differences for review, payments, rates,
 * real balances and schedule. */
export function LoanCard({ loan, today }: { loan: Loan; today: string }) {
  const titleId = useId()
  const share = progress(loan)
  return (
    <article
      data-testid="loan-card"
      aria-labelledby={titleId}
      className="flex min-w-0 flex-col gap-5"
    >
      <section className={cn(PANEL, 'flex flex-col gap-4 px-5 py-5 sm:px-6')}>
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <h1 id={titleId} className="text-[22px] font-bold tracking-tight break-words sm:text-[26px]">
              {loan.name}
            </h1>
            <span className="text-[13px] text-muted-foreground tabular-nums">
              {t('loans.card.number', { last: loan.number.slice(-4) })} ·{' '}
              {t('loans.card.rate', { rate: rateText(loan.rate_bp) })}
            </span>
          </div>
          <EditLoan loan={loan} />
        </header>
        <div className="flex flex-col gap-1" aria-label={t('loans.card.balance')}>
          <span className="text-[13px] font-semibold text-muted-foreground">
            {t('loans.card.balance')}
          </span>
          <span data-testid="loan-balance" className="text-[32px] leading-none font-bold tabular-nums">
            {balanceText(loan)}
          </span>
          <span className="text-[13px] text-muted-foreground tabular-nums">
            {t('loans.card.of', { amount: formatMoney(loan.principal_cents, loan.currency) })} ·{' '}
            {t('loans.card.progress', { share: `${Math.round(share * 100)} %` })} ·{' '}
            <span data-testid="loan-remaining">{remainingLine(loan)}</span>
          </span>
        </div>
        <LoanChart loan={loan} today={today} />
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 border-t border-border pt-4 sm:grid-cols-3">
          <Figure term={t('loans.card.next')}>
            {loan.next_due !== null && loan.next_payment_cents !== null ? (
              t('loans.card.nextLine', {
                amount: formatMoney(loan.next_payment_cents, loan.currency),
                day: longDay(loan.next_due),
              })
            ) : (
              <span>—</span>
            )}
          </Figure>
          <Figure term={t('loans.card.paid')}>
            <span className="font-semibold">{formatMoney(loan.paid_cents, loan.currency)}</span>
            <span className="text-xs text-muted-foreground">{paidLine(loan)}</span>
          </Figure>
          <Figure term={t('loans.card.interest')}>
            <span data-testid="loan-interest">{interestLine(loan)}</span>
          </Figure>
        </dl>
      </section>
      {loan.differences.length > 0 && <Differences loan={loan} />}
      <section className={cn(PANEL, 'flex flex-col gap-5 px-5 py-5 sm:px-6')}>
        <LoanPayments loan={loan} />
        <LoanEstimates loan={loan} />
      </section>
      <details data-testid="loan-details" className={cn(PANEL, 'group px-5 py-1 sm:px-6')}>
        <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between text-[15px] font-semibold [&::-webkit-details-marker]:hidden">
          {t('loans.details.title')}
          <ChevronDown
            size={18}
            aria-hidden="true"
            className="text-muted-foreground transition-transform group-open:rotate-180"
          />
        </summary>
        <div className="flex flex-col gap-5 pb-5">
          <p className="text-[13px] text-muted-foreground">
            {t('loans.card.statements', { count: loan.statement_months })}
          </p>
          <LoanRates loan={loan} />
          <LoanInstallments loan={loan} />
          <LoanBalances loan={loan} />
          <LoanSchedule loan={loan} />
        </div>
      </details>
    </article>
  )
}

/** The balance from the start: what is past solid, the schedule ahead dashed. */
function LoanChart({ loan, today }: { loan: Loan; today: string }) {
  const points = [
    { day: loan.start_date, value: -loan.principal_cents },
    ...loan.schedule.map((row) => ({ day: row.due, value: -row.balance_cents })),
  ]
  const ahead = points.findIndex((p) => p.day > today)
  return (
    <BalanceChart
      points={points}
      format={(cents) => formatMoney(cents, loan.currency)}
      projectedFrom={ahead < 0 ? undefined : ahead}
    />
  )
}

function Figure({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[13px] font-semibold text-muted-foreground">{term}</dt>
      <dd className="flex flex-col text-sm tabular-nums">{children}</dd>
    </div>
  )
}

function Differences({ loan }: { loan: Loan }) {
  return (
    <section
      data-testid="loan-differences"
      aria-label={t('loans.difference.title')}
      className="flex flex-col gap-1.5 rounded-xl bg-up-soft px-4 py-3 text-[13px] text-up-ink"
    >
      <h3 className="flex items-center gap-1.5 font-semibold">
        <TriangleAlert size={14} aria-hidden="true" />
        {t('loans.difference.title')}
      </h3>
      <ul className="flex flex-col gap-1">
        {loan.differences.map((d) => (
          <li key={`${d.kind}-${d.month}`}>{differenceText(loan, d)}</li>
        ))}
      </ul>
    </section>
  )
}

function EditLoan({ loan }: { loan: Loan }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <Action label={t('loans.card.editLabel', { name: loan.name })} onClick={() => setOpen(true)}>
        <Pencil size={15} aria-hidden="true" />
        {t('loans.card.edit')}
      </Action>
      {open && <LoanFormSheet loan={loan} onClose={() => setOpen(false)} />}
    </div>
  )
}
