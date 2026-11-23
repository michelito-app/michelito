import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { estimateText } from '@/lib/loans'
import { SectionTitle } from './parts'

/** The payments the loan estimates where none is linked: marked as such, never editable (they go
 * away on their own when the payment is linked or the loan statement arrives). */
export function LoanEstimates({ loan }: { loan: Loan }) {
  if (loan.estimates.length === 0) return null
  return (
    <section data-testid="loan-estimates" className="flex flex-col gap-2">
      <SectionTitle>{t('loans.estimates.title')}</SectionTitle>
      <p className="text-[13px] text-muted-foreground">{t('loans.estimates.hint')}</p>
      <ul className="flex flex-col divide-y divide-border rounded-xl border border-dashed border-border">
        {loan.estimates.map((estimate) => {
          const text = estimateText(loan, estimate)
          return (
            <li key={`${estimate.kind}-${estimate.day}`} className="flex flex-col px-3 py-2">
              <span className="text-sm font-semibold text-muted-foreground tabular-nums">
                {text.amount}
              </span>
              <span className="text-xs text-muted-foreground">{text.note}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
