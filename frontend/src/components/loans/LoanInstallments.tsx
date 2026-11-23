import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { parseCents } from '@/lib/links'
import { useLoanInstallment } from '@/lib/loanQueries'
import { installmentText } from '@/lib/loans'
import { dayWithYear } from '@/lib/months'
import { DatedEntries } from './DatedEntries'

/** What the bank charges each month, from a day on: the schedule uses it instead of its own. */
export function LoanInstallments({ loan }: { loan: Loan }) {
  const change = useLoanInstallment()
  return (
    <DatedEntries
      testId="loan-installments"
      title={t('loans.installments.title')}
      hint={t('loans.installments.hint')}
      entries={loan.installments.map((entry) => {
        const day = dayWithYear(entry.effective)
        return {
          day: entry.effective,
          text: installmentText(entry.installment_cents, loan.currency),
          note: t('loans.installments.since', { day }),
          removeLabel: t('loans.installments.removeLabel', { day }),
        }
      })}
      labels={{
        add: t('loans.installments.add'),
        day: t('loans.installments.day'),
        value: t('loans.installments.amount'),
        save: t('loans.installments.save'),
        invalid: t('loans.installments.invalid'),
        remove: t('loans.installments.remove'),
      }}
      parse={parseCents}
      busy={change.isPending}
      error={change.error}
      onSave={(day, value, done) => change.mutate({ id: loan.id, day, value }, { onSuccess: done })}
      onRemove={(day) => change.mutate({ id: loan.id, day, value: null })}
    />
  )
}
