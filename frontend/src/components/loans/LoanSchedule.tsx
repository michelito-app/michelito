import { useId, useState } from 'react'
import { Action } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import { dayWithYear } from '@/lib/months'
import { cn } from '@/lib/utils'

const CELL = 'px-2 py-1.5 text-right tabular-nums whitespace-nowrap'

/** The amortization schedule, folded: each installment's payment, interest, principal and the
 * balance after it (the months with a loan statement say so). */
export function LoanSchedule({ loan }: { loan: Loan }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const money = (cents: number) => formatMoney(cents, loan.currency)
  return (
    <section className="flex flex-col gap-2">
      <div>
        <Action disclosure={{ expanded: open, controls: id }} onClick={() => setOpen(!open)}>
          {open ? t('loans.schedule.hide') : t('loans.schedule.show')}
        </Action>
      </div>
      {open && (
        <div id={id} className="max-h-96 overflow-auto rounded-xl border border-border">
          <table className="w-full text-[13px]">
            <caption className="sr-only">{t('loans.schedule.title')}</caption>
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th scope="col" className={cn(CELL, 'text-left')}>{t('loans.schedule.number')}</th>
                <th scope="col" className={cn(CELL, 'text-left')}>{t('loans.schedule.due')}</th>
                <th scope="col" className={CELL}>{t('loans.schedule.payment')}</th>
                <th scope="col" className={CELL}>{t('loans.schedule.interest')}</th>
                <th scope="col" className={CELL}>{t('loans.schedule.principal')}</th>
                <th scope="col" className={CELL}>{t('loans.schedule.balance')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loan.schedule.map((row) => (
                <tr key={row.number} data-source={row.source}>
                  <td className={cn(CELL, 'text-left')}>{row.number}</td>
                  <td className={cn(CELL, 'text-left')}>
                    {dayWithYear(row.due)}
                    {row.source === 'statement' && (
                      <span className="ml-1 text-primary">· {t('loans.schedule.fromStatement')}</span>
                    )}
                  </td>
                  <td className={CELL}>{money(row.payment_cents)}</td>
                  <td className={CELL}>{money(row.interest_cents)}</td>
                  <td className={CELL}>{money(row.principal_cents)}</td>
                  <td className={CELL}>{money(row.balance_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
