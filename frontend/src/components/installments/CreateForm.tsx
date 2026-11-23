import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { InstallmentDraft, InstallmentPerson, InstallmentPlan } from '@/lib/api'
import {
  createBody,
  initialForm,
  numberAsk,
  numbering,
  type PlanForm,
} from '@/lib/installmentForm'
import { useCreateInstallment } from '@/lib/installmentQueries'
import { formatMoney } from '@/lib/links'
import { EarlierCharges } from './EarlierCharges'
import { Field, FormAlert, NameInput, NumberInput } from './formParts'
import { OwnerField } from './OwnerField'

interface CreateFormProps {
  draft: InstallmentDraft
  people: readonly InstallmentPerson[]
  preferred: number | null
  onCreated: (plan: InstallmentPlan) => void
}

/** The short "It is an installment…" form: the number of installments and the owner ("For") are what the
 * user fills; which installment it is comes from the checked earlier charges (typed only when
 * it cannot be deduced or does not fit); the name is prefilled. */
export function CreateForm({ draft, people, preferred, onCreated }: CreateFormProps) {
  const create = useCreateInstallment()
  const [form, setForm] = useState<PlanForm>(() => initialForm(draft, preferred))
  const [invalid, setInvalid] = useState<string | null>(null)
  const numbers = numbering(draft, form.checked)
  const ask = numberAsk(draft, numbers.number, form.count)

  function change(patch: Partial<PlanForm>) {
    setForm((current) => ({ ...current, ...patch }))
    setInvalid(null)
  }

  function submit() {
    const result = createBody(draft, form)
    if (result.error !== null) return setInvalid(result.error)
    create.mutate(result.body, { onSuccess: onCreated })
  }

  return (
    <form
      data-testid="installment-form"
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <p className="text-[13px] text-ink-2">
        {t('installments.form.each', {
          amount: formatMoney(draft.amount_cents, draft.currency),
          account: draft.account_label,
        })}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('installments.form.count')}>
          <NumberInput value={form.count} onChange={(count) => change({ count })} />
        </Field>
        <OwnerField people={people} value={form} onChange={change} />
      </div>
      <NumberLine ask={ask} deduced={numbers.number} form={form} onChange={change} />
      <EarlierCharges
        draft={draft}
        checked={form.checked}
        numbers={numbers}
        onChange={(checked) => change({ checked })}
      />
      <Field label={t('installments.form.name')} hint={t('installments.form.nameHint')}>
        <NameInput value={form.name} onChange={(name) => change({ name })} />
      </Field>
      {invalid && <FormAlert>{invalid}</FormAlert>}
      {create.isError && (
        <FormAlert>{t('installments.form.saveError', { message: create.error.message })}</FormAlert>
      )}
      <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={create.isPending}>
        {create.isPending ? t('installments.form.saving') : t('installments.form.submit')}
      </Button>
    </form>
  )
}

interface NumberLineProps {
  ask: ReturnType<typeof numberAsk>
  deduced: number
  form: PlanForm
  onChange: (patch: Partial<PlanForm>) => void
}

/** "This is installment 3 of 6", or the question when it cannot be deduced or does not fit. */
function NumberLine({ ask, deduced, form, onChange }: NumberLineProps) {
  if (ask === null) {
    return (
      <p data-testid="installment-position" className="text-sm font-semibold tabular-nums">
        {t('installments.form.position', { number: deduced, count: form.count.trim() })}
      </p>
    )
  }
  const why =
    ask === 'unknown'
      ? t('installments.form.numberUnknown')
      : t('installments.form.numberOver', { count: form.count.trim(), number: deduced })
  return (
    <div className="flex flex-col gap-1.5">
      <p data-testid="installment-number-why" className="text-[13px] text-up-ink">
        {why}
      </p>
      <div className="max-w-[12rem]">
        <Field label={t('installments.form.number')}>
          <NumberInput value={form.number} min={1} onChange={(number) => onChange({ number })} />
        </Field>
      </div>
    </div>
  )
}
