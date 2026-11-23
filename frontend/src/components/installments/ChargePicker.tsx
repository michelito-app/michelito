import { ChevronRight } from 'lucide-react'
import { FOCUS } from '@/components/summary/styles'
import { LoadFailure } from '@/components/transactions/linkParts'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { InstallmentCharge } from '@/lib/api'
import { useInstallmentCharges } from '@/lib/installmentQueries'
import { formatMoney } from '@/lib/links'
import { dayWithYear } from '@/lib/months'
import { cn } from '@/lib/utils'

interface ChargePickerProps {
  /** A plan: the charges it can link, each with the installment it would be. */
  planId?: number | null
  empty: string
  disabled?: boolean
  onPick: (charge: InstallmentCharge) => void
}

/** Recent card charges to choose one from: merchant, date, card and amount. */
export function ChargePicker({ planId = null, empty, disabled, onPick }: ChargePickerProps) {
  const charges = useInstallmentCharges(planId)
  if (charges.isError) {
    return <LoadFailure what={t('installments.picker.loadWhat')} error={charges.error} />
  }
  if (charges.isPending) {
    return (
      <div aria-busy="true" className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-14 w-full rounded-xl" />
        ))}
      </div>
    )
  }
  if (charges.data.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{empty}</p>
  }
  return (
    <ul data-testid="installment-charges" className="flex flex-col gap-2">
      {charges.data.map((charge) => (
        <li key={charge.fingerprint}>
          <ChargeButton charge={charge} disabled={disabled} onPick={() => onPick(charge)} />
        </li>
      ))}
    </ul>
  )
}

function ChargeButton({
  charge,
  disabled,
  onPick,
}: {
  charge: InstallmentCharge
  disabled?: boolean
  onPick: () => void
}) {
  const day = dayWithYear(charge.day)
  const label =
    charge.number === null
      ? undefined
      : t('installments.edit.addLabel', { merchant: charge.merchant, day, number: charge.number })
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onPick}
      className={cn(
        'flex min-h-14 w-full items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-[#F6FAF8] active:bg-[#EEF5F1] disabled:cursor-not-allowed disabled:opacity-60',
        FOCUS,
      )}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-sm font-semibold">{charge.merchant}</span>
        <span className="truncate text-xs text-muted-foreground">
          {t('installments.picker.line', { day, account: charge.account_label })}
        </span>
        {charge.number !== null && (
          <span className="text-xs font-semibold text-primary">
            {t('installments.picker.would', { number: charge.number })}
          </span>
        )}
      </span>
      <span className="shrink-0 text-sm font-semibold tabular-nums">
        {formatMoney(charge.amount_cents, charge.currency)}
      </span>
      <ChevronRight size={16} aria-hidden="true" className="shrink-0 text-muted-foreground" />
    </button>
  )
}
