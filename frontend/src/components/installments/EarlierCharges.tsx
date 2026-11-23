import { t } from '@/i18n'
import type { InstallmentDraft } from '@/lib/api'
import type { Numbering } from '@/lib/installmentForm'
import { formatMoney } from '@/lib/links'
import { dayWithYear } from '@/lib/months'
import { cn } from '@/lib/utils'

interface EarlierChargesProps {
  draft: InstallmentDraft
  checked: readonly string[]
  numbers: Numbering
  onChange: (checked: string[]) => void
}

/** "I found N earlier identical charges on this card": each one (date, amount) checked, as
 * "Cuota 1", "Cuota 2"…; unchecking one renumbers the rest. */
export function EarlierCharges({ draft, checked, numbers, onChange }: EarlierChargesProps) {
  if (draft.earlier.length === 0) return null
  function toggle(fingerprint: string, on: boolean) {
    onChange(
      on ? [...checked, fingerprint] : checked.filter((current) => current !== fingerprint),
    )
  }
  return (
    <fieldset data-testid="installment-earlier" className="flex flex-col gap-2">
      <legend className="pb-1 text-[13px] font-semibold text-ink-2">
        {t('installments.form.found', { count: draft.earlier.length })}
      </legend>
      <p className="-mt-1 text-xs text-muted-foreground">{t('installments.form.foundHint')}</p>
      <ul className="flex flex-col divide-y divide-border rounded-xl border border-border">
        {draft.earlier.map((charge) => {
          const number = numbers.earlier.get(charge.fingerprint)
          const on = number !== undefined
          return (
            <li key={charge.fingerprint}>
              <label className="flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  checked={checked.includes(charge.fingerprint)}
                  onChange={(event) => toggle(charge.fingerprint, event.target.checked)}
                  className="size-[18px] shrink-0 cursor-pointer accent-primary"
                />
                <span
                  data-testid="installment-earlier-number"
                  className={cn('w-20 shrink-0 font-semibold', on ? 'text-primary' : 'text-muted-foreground')}
                >
                  {on
                    ? t('installments.form.earlierNumber', { number })
                    : t('installments.form.earlierSkipped')}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink-2">{dayWithYear(charge.day)}</span>
                <span className="shrink-0 font-medium tabular-nums">
                  {formatMoney(charge.amount_cents, draft.currency)}
                </span>
              </label>
            </li>
          )
        })}
      </ul>
    </fieldset>
  )
}
