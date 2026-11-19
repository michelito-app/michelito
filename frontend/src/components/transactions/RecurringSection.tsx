import { Check } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import type { RecurringGroupKey, Tx, TxRecurringBody } from '@/lib/api'
import { useMarkTxRecurring, useTxRecurring } from '@/lib/queries'
import { GROUP_OPTIONS, MAX_INSTALLMENTS, parseInstallments, txRecurringBody } from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { Action, FIELD, SECTION, SECTION_TITLE } from './linkParts'

const LINK = 'inline-flex min-h-11 items-center font-semibold text-primary'

/** In the detail of a debit: mark it as recurring (cadence, group and, for a loan, installments)
 * or, if it already is, where it is in Recurring. Marks the merchant or its provider. */
export function RecurringSection({ tx }: { tx: Tx }) {
  const debit = tx.kind === 'expense' && tx.amount_cents > 0
  const state = useTxRecurring(tx.fingerprint, debit)
  const [open, setOpen] = useState(false)
  if (!debit || !state.data) return null
  const data = state.data
  if (data.recurring) {
    return (
      <section aria-label={t('transactions.recurring.title')} className={SECTION}>
        <h3 className={SECTION_TITLE}>{t('transactions.recurring.title')}</h3>
        <p data-testid="recurring-state" className="text-[13px] text-ink-2">
          {tn('transactions.recurring.state', {
            name: <span className="font-semibold">{data.name}</span>,
          })}
          {data.group && ` · ${data.group}`}
        </p>
        <Link to="/recurring" className={LINK}>
          {t('transactions.recurring.see')}
        </Link>
      </section>
    )
  }
  if (!data.eligible) return null
  return (
    <section aria-label={t('transactions.recurring.title')} className={SECTION}>
      <h3 className={SECTION_TITLE}>{t('transactions.recurring.title')}</h3>
      {!open ? (
        <div>
          <Action onClick={() => setOpen(true)}>{t('transactions.recurring.open')}</Action>
        </div>
      ) : (
        <RecurringForm tx={tx} name={data.name} loan={data.loan} onCancel={() => setOpen(false)} />
      )}
    </section>
  )
}

interface RecurringFormProps {
  tx: Tx
  name: string
  loan: boolean
  onCancel: () => void
}

function RecurringForm({ tx, name, loan, onCancel }: RecurringFormProps) {
  const ids = useId()
  const save = useMarkTxRecurring()
  const [cadence, setCadence] = useState<TxRecurringBody['cadence']>('monthly')
  const [group, setGroup] = useState<RecurringGroupKey | ''>(loan ? 'loans' : '')
  const [left, setLeft] = useState('')
  const [invalid, setInvalid] = useState(false)
  const isLoan = loan || group === 'loans'

  function submit() {
    const installments = isLoan && left.trim() !== '' ? parseInstallments(left) : null
    if (isLoan && left.trim() !== '' && installments === null) {
      setInvalid(true)
      return
    }
    save.mutate({
      fingerprint: tx.fingerprint,
      body: txRecurringBody(cadence, group, installments),
    })
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <p className="text-[13px] text-ink-2">
        {tn('transactions.recurring.intro', { name: <span className="font-semibold">{name}</span> })}
      </p>
      <fieldset className="flex flex-wrap gap-2">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">
          {t('transactions.recurring.cadence')}
        </legend>
        {(['monthly', 'yearly'] as const).map((value) => (
          <label
            key={value}
            className={cn(
              'flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm',
              cadence === value ? 'border-primary bg-[#F6FAF8]' : 'border-border',
            )}
          >
            <input
              type="radio"
              name={`${ids}-cadence`}
              value={value}
              checked={cadence === value}
              onChange={() => setCadence(value)}
              className="size-[18px] cursor-pointer accent-primary"
            />
            {value === 'monthly'
              ? t('transactions.recurring.monthly')
              : t('transactions.recurring.yearly')}
          </label>
        ))}
      </fieldset>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
        {t('transactions.recurring.group')}
        <select
          aria-label={t('transactions.recurring.group')}
          value={group}
          onChange={(event) => setGroup(event.target.value as RecurringGroupKey | '')}
          className={cn(FIELD, 'cursor-pointer font-medium')}
        >
          <option value="">{t('transactions.recurring.byCategory')}</option>
          {GROUP_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {isLoan && (
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
          {t('transactions.recurring.installments')}
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_INSTALLMENTS}
            step={1}
            value={left}
            aria-invalid={invalid}
            aria-describedby={invalid ? `${ids}-hint` : undefined}
            onChange={(event) => {
              setLeft(event.target.value)
              setInvalid(false)
            }}
            className={cn(FIELD, 'w-32 tabular-nums aria-invalid:border-up')}
          />
          {invalid && (
            <span id={`${ids}-hint`} className="font-normal text-up-ink">
              {t('transactions.recurring.installmentsHint', { max: MAX_INSTALLMENTS })}
            </span>
          )}
        </label>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex h-11 cursor-pointer items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60"
        >
          {save.isPending ? t('transactions.saving') : t('transactions.recurring.submit')}
        </button>
        <Action onClick={onCancel} disabled={save.isPending}>
          {t('transactions.cancel')}
        </Action>
      </div>
      {save.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('transactions.saveError', { message: save.error.message })}
        </p>
      )}
      {save.isSuccess && (
        <p role="status" className="inline-flex items-center gap-1.5 text-[13px] text-primary">
          <Check size={14} aria-hidden="true" />
          {t('transactions.saved')}
        </p>
      )}
    </form>
  )
}
