import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import { useLoanBalance } from '@/lib/loanQueries'
import { dayWithYear } from '@/lib/months'
import { DatedEntries } from './DatedEntries'

/** "0" is a valid balance (paid off); otherwise like any amount. */
function parseBalance(text: string): number | null {
  const clean = text.trim().replace(/^(RD|US)?\$\s*/i, '').replaceAll(',', '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  return Math.round(Number(clean) * 100)
}

/** Real balances from the bank: the schedule is recomputed from each one on. */
export function LoanBalances({ loan }: { loan: Loan }) {
  const change = useLoanBalance()
  return (
    <DatedEntries
      testId="loan-balances"
      title={t('loans.balances.title')}
      hint={t('loans.balances.hint')}
      entries={loan.balances.map((balance) => {
        const day = dayWithYear(balance.day)
        return {
          day: balance.day,
          text: formatMoney(balance.balance_cents, loan.currency),
          note: t('loans.balances.on', { day }),
          removeLabel: t('loans.balances.removeLabel', { day }),
        }
      })}
      labels={{
        add: t('loans.balances.add'),
        day: t('loans.balances.day'),
        value: t('loans.balances.amount'),
        save: t('loans.balances.save'),
        invalid: t('loans.balances.invalid'),
        remove: t('loans.balances.remove'),
      }}
      parse={parseBalance}
      busy={change.isPending}
      error={change.error}
      onSave={(day, value, done) => change.mutate({ id: loan.id, day, value }, { onSuccess: done })}
      onRemove={(day) => change.mutate({ id: loan.id, day, value: null })}
    />
  )
}
