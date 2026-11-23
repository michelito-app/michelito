import { Ellipsis } from 'lucide-react'
import { useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Action, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import { useLoanPayment } from '@/lib/loanQueries'
import { dayWithYear } from '@/lib/months'
import { cn } from '@/lib/utils'
import { LinkPaymentSheet } from './LinkPaymentSheet'
import { SectionTitle } from './parts'

const SHOWN = 6

/** The linked payments, newest first: "it is not this loan's" on each, "Link a payment". */
export function LoanPayments({ loan }: { loan: Loan }) {
  const [all, setAll] = useState(false)
  const [linking, setLinking] = useState(false)
  const [menu, setMenu] = useState<string | null>(null)
  const change = useLoanPayment()
  const shown = all ? loan.payments : loan.payments.slice(0, SHOWN)
  const hidden = loan.payments.length - shown.length
  return (
    <section data-testid="loan-payments" className="flex flex-col gap-2">
      <SectionTitle>{t('loans.payments.title')}</SectionTitle>
      {loan.payments.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('loans.payments.empty')}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-xl border border-border">
          {shown.map((p) => (
            <li key={p.fingerprint} className="flex flex-col px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm font-semibold tabular-nums">
                    {formatMoney(p.amount_cents, loan.currency)}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {dayWithYear(p.day)} · {p.account_label}
                    {p.origin === 'confirmed' && ` · ${t('loans.payments.byHand')}`}
                  </span>
                </span>
                <button
                  type="button"
                  aria-expanded={menu === p.fingerprint}
                  aria-label={t('loans.payments.menu', {
                    day: dayWithYear(p.day),
                    amount: formatMoney(p.amount_cents, loan.currency),
                  })}
                  onClick={() => setMenu(menu === p.fingerprint ? null : p.fingerprint)}
                  className={cn(
                    'inline-flex size-11 flex-none cursor-pointer items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground',
                    FOCUS,
                  )}
                >
                  <Ellipsis size={18} aria-hidden="true" />
                </button>
              </div>
              {menu === p.fingerprint && (
                <div className="flex justify-end pt-1">
                  <Action
                    label={t('loans.payments.unlinkLabel', {
                      day: dayWithYear(p.day),
                      amount: formatMoney(p.amount_cents, loan.currency),
                    })}
                    disabled={change.isPending}
                    onClick={() =>
                      change.mutate(
                        { id: loan.id, fingerprint: p.fingerprint, linked: false },
                        { onSuccess: () => setMenu(null) },
                      )
                    }
                  >
                    {t('loans.payments.unlink')}
                  </Action>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Failure error={change.error} />
      <div className="flex flex-wrap gap-2">
        {hidden > 0 && (
          <Action onClick={() => setAll(true)}>
            {t('loans.payments.more', { count: hidden })}
          </Action>
        )}
        <Action onClick={() => setLinking(true)}>{t('loans.payments.link')}</Action>
      </div>
      {linking && <LinkPaymentSheet loan={loan} onClose={() => setLinking(false)} />}
    </section>
  )
}
