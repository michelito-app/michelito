import { useState } from 'react'
import { Field, FormAlert } from '@/components/installments/formParts'
import { FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { Loan, LoanCurrency } from '@/lib/api'
import { useCreateLoan, useEditLoan } from '@/lib/loanQueries'
import {
  emptyForm,
  formOf,
  loanBody,
  loanEdit,
  type LoanForm,
  NAME_MAX,
  NUMBER_MAX,
  TERM_MAX,
} from '@/lib/loans'
import { localToday } from '@/lib/months'
import { cn } from '@/lib/utils'
import { DeleteLoan } from './DeleteLoan'

interface LoanFormSheetProps {
  /** null: a new loan. */
  loan: Loan | null
  onClose: () => void
  onSaved?: (loan: Loan) => void
}

/** "New loan" or "Edit loan": name, number, the contract; editing also offers "Delete". */
export function LoanFormSheet({ loan, onClose, onSaved }: LoanFormSheetProps) {
  const create = useCreateLoan()
  const edit = useEditLoan()
  const [form, setForm] = useState<LoanForm>(() =>
    loan === null ? emptyForm(localToday()) : formOf(loan),
  )
  const [invalid, setInvalid] = useState<string | null>(null)
  const saving = create.isPending || edit.isPending
  const failure = create.error ?? edit.error

  function change(patch: Partial<LoanForm>) {
    setForm((before) => ({ ...before, ...patch }))
    setInvalid(null)
  }

  function done(saved: Loan | void) {
    if (saved) onSaved?.(saved)
    onClose()
  }

  function submit() {
    if (loan === null) {
      const result = loanBody(form)
      if (result.error !== null) return setInvalid(result.error)
      return create.mutate(result.body, { onSuccess: done })
    }
    const result = loanEdit(loan, form)
    if (result.error !== null) return setInvalid(result.error)
    if (Object.keys(result.body).length === 0) return onClose()
    edit.mutate({ id: loan.id, body: result.body }, { onSuccess: done })
  }

  return (
    <BottomSheet
      title={loan === null ? t('loans.form.title') : t('loans.form.editTitle')}
      onClose={onClose}
      full
    >
      <form
        data-testid="loan-form"
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <Field label={t('loans.form.name')} hint={t('loans.form.nameHint')}>
          <input
            value={form.name}
            maxLength={NAME_MAX}
            onChange={(event) => change({ name: event.target.value })}
            className={FIELD}
          />
        </Field>
        <Field label={t('loans.form.number')} hint={t('loans.form.numberHint')}>
          <input
            value={form.number}
            maxLength={NUMBER_MAX}
            inputMode="numeric"
            autoComplete="off"
            onChange={(event) => change({ number: event.target.value })}
            className={cn(FIELD, 'tabular-nums')}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <Field label={t('loans.form.principal')}>
            <input
              value={form.principal}
              inputMode="decimal"
              onChange={(event) => change({ principal: event.target.value })}
              className={cn(FIELD, 'tabular-nums')}
            />
          </Field>
          <Field label={t('loans.form.currency')}>
            <select
              value={form.currency}
              disabled={loan !== null}
              onChange={(event) => change({ currency: event.target.value as LoanCurrency })}
              className={FIELD}
            >
              <option value="DOP">RD$</option>
              <option value="USD">US$</option>
            </select>
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {loan === null && (
            <Field label={t('loans.form.rate')} hint={t('loans.form.rateHint')}>
              <input
                value={form.rate}
                inputMode="decimal"
                onChange={(event) => change({ rate: event.target.value })}
                className={cn(FIELD, 'tabular-nums')}
              />
            </Field>
          )}
          <Field label={t('loans.form.term')}>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={TERM_MAX}
              value={form.term}
              onChange={(event) => change({ term: event.target.value })}
              className={cn(FIELD, 'tabular-nums')}
            />
          </Field>
        </div>
        <Field label={t('loans.form.start')} hint={t('loans.form.startHint')}>
          <input
            type="date"
            value={form.start}
            onChange={(event) => change({ start: event.target.value })}
            className={FIELD}
          />
        </Field>
        <p className="text-[13px] text-ink-2">{t('loans.form.spending')}</p>
        {invalid && <FormAlert>{invalid}</FormAlert>}
        {failure && <FormAlert>{t('loans.form.saveError', { message: failure.message })}</FormAlert>}
        <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={saving}>
          {saving
            ? t('loans.form.saving')
            : loan === null
              ? t('loans.form.submit')
              : t('loans.form.save')}
        </Button>
      </form>
      {loan !== null && <DeleteLoan loan={loan} onDeleted={onClose} />}
    </BottomSheet>
  )
}
