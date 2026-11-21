import { useState } from 'react'
import { Action, FIELD, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { CashBox, CashCurrency } from '@/lib/api'
import { countCurrencies, countsBody } from '@/lib/cashBox'
import { formatMoney } from '@/lib/links'
import { useChangeCashBox } from '@/lib/queries'

const LABEL = 'flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2'
const SYMBOL: Record<CashCurrency, string> = { DOP: 'RD$', USD: 'US$' }

interface ReconcileFormProps {
  box: CashBox
  onDone: () => void
}

/** "Reconcile cash": how much cash there is now per currency; the difference becomes one entry
 * of this month (one undo). */
export function ReconcileForm({ box, onDone }: ReconcileFormProps) {
  const change = useChangeCashBox()
  const [typed, setTyped] = useState<Partial<Record<CashCurrency, string>>>({})
  const [error, setError] = useState<string | null>(null)

  function save() {
    const body = countsBody(typed)
    if (typeof body === 'string') {
      setError(body)
      return
    }
    change.mutate({ action: 'reconcile', counts: body }, { onSuccess: onDone })
  }

  return (
    <section
      aria-label={t('cashBox.reconcile.title')}
      className="flex flex-col gap-3 rounded-xl border border-border px-3.5 py-3"
    >
      <h3 className="text-sm font-semibold">{t('cashBox.reconcile.title')}</h3>
      <p className="text-[13px] text-muted-foreground">{t('cashBox.reconcile.intro')}</p>
      <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
        {countCurrencies(box).map((currency) => {
          // Up to today, the figure the server compares with (later entries wait).
          const now = box.balances_today.find((b) => b.currency === currency)?.amount_cents ?? 0
          return (
            <label key={currency} className={LABEL}>
              {t('cashBox.reconcile.have', { currency: SYMBOL[currency] })}
              <input
                className={FIELD}
                inputMode="decimal"
                autoComplete="off"
                placeholder="0.00"
                value={typed[currency] ?? ''}
                onChange={(event) => {
                  setTyped((current) => ({ ...current, [currency]: event.target.value }))
                  setError(null)
                  change.reset()
                }}
              />
              <span className="font-normal text-muted-foreground">
                {t('cashBox.reconcile.computed', { amount: formatMoney(now, currency) })}
              </span>
            </label>
          )
        })}
      </div>
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {error}
        </p>
      )}
      <Failure error={change.error} />
      <div className="flex flex-wrap gap-2">
        <Action primary disabled={change.isPending} onClick={save}>
          {change.isPending ? t('cashBox.form.saving') : t('cashBox.reconcile.save')}
        </Action>
        <Action onClick={onDone}>{t('cashBox.form.cancel')}</Action>
      </div>
    </section>
  )
}
