import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { useLoanRate } from '@/lib/loanQueries'
import { parseRate, rateText } from '@/lib/loans'
import { dayWithYear } from '@/lib/months'
import { DatedEntries } from './DatedEntries'

/** The rate history: the contract's rate and each change from its day on. */
export function LoanRates({ loan }: { loan: Loan }) {
  const change = useLoanRate()
  return (
    <DatedEntries
      testId="loan-rates"
      title={t('loans.rates.title')}
      entries={loan.rates.map((rate) => {
        const day = dayWithYear(rate.effective)
        const starting = rate.effective <= loan.start_date
        return {
          day: rate.effective,
          text: rateText(rate.rate_bp),
          note: starting
            ? `${t('loans.rates.since', { day })} · ${t('loans.rates.contract')}`
            : t('loans.rates.since', { day }),
          removeLabel: starting ? null : t('loans.rates.removeLabel', { day }),
        }
      })}
      labels={{
        add: t('loans.rates.add'),
        day: t('loans.rates.day'),
        value: t('loans.rates.rate'),
        save: t('loans.rates.save'),
        invalid: t('loans.rates.invalid'),
        remove: t('loans.rates.remove'),
      }}
      parse={parseRate}
      busy={change.isPending}
      error={change.error}
      onSave={(day, value, done) => change.mutate({ id: loan.id, day, value }, { onSuccess: done })}
      onRemove={(day) => change.mutate({ id: loan.id, day, value: null })}
    />
  )
}
