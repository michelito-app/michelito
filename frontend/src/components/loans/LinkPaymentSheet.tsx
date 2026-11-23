import { useState } from 'react'
import { Field } from '@/components/installments/formParts'
import { Action, FIELD, Failure, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import { useLoanCandidates, useLoanPayment } from '@/lib/loanQueries'
import { dayWithYear } from '@/lib/months'

/** "Link a payment": recent charges not in a loan, searchable; choosing one links it. */
export function LinkPaymentSheet({ loan, onClose }: { loan: Loan; onClose: () => void }) {
  const [q, setQ] = useState('')
  const candidates = useLoanCandidates(loan.id, q)
  const link = useLoanPayment()
  return (
    <BottomSheet title={t('loans.link.title')} onClose={onClose} full>
      <p className="text-[13px] text-ink-2">{t('loans.link.hint')}</p>
      <Field label={t('loans.link.search')}>
        <input
          type="search"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          className={FIELD}
        />
      </Field>
      {candidates.isError ? (
        <LoadFailure what={t('loans.link.what')} error={candidates.error} />
      ) : candidates.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-2">
          <Skeleton className="h-14 w-full rounded-xl" />
          <Skeleton className="h-14 w-full rounded-xl" />
        </div>
      ) : candidates.data.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('loans.link.empty')}</p>
      ) : (
        <ul data-testid="loan-candidates" className="flex flex-col divide-y divide-border rounded-xl border border-border">
          {candidates.data.map((c) => {
            const amount = formatMoney(c.amount_cents, loan.currency)
            return (
              <li key={c.fingerprint} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-semibold">{c.description}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {dayWithYear(c.day)} · {c.account_label} · {amount}
                  </span>
                </span>
                <Action
                  primary
                  label={t('loans.link.chooseLabel', { day: dayWithYear(c.day), amount })}
                  disabled={link.isPending}
                  onClick={() =>
                    link.mutate(
                      { id: loan.id, fingerprint: c.fingerprint, linked: true },
                      { onSuccess: onClose },
                    )
                  }
                >
                  {t('loans.link.choose')}
                </Action>
              </li>
            )
          })}
        </ul>
      )}
      <Failure error={link.error} />
    </BottomSheet>
  )
}
