import { useState } from 'react'
import { FIELD, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { InstallmentPerson, InstallmentPlan } from '@/lib/api'
import {
  type EditForm,
  editBody,
  initialEdit,
  ownerChanged,
  ownerChoices,
} from '@/lib/installmentForm'
import { useEditInstallment, useInstallmentPeople } from '@/lib/installmentQueries'
import { NAME_MAX } from '@/lib/installments'
import { DeletePlan } from './DeletePlan'
import { Field, FormAlert, NumberInput } from './formParts'
import { OwnerField } from './OwnerField'
import { PlanCharges } from './PlanCharges'

interface EditPlanSheetProps {
  plan: InstallmentPlan
  onClose: () => void
}

/** "Edit plan": its name, number of installments and owner; its charges (remove one, add
 * one); and "Delete plan". */
export function EditPlanSheet({ plan, onClose }: EditPlanSheetProps) {
  const people = useInstallmentPeople()
  return (
    <BottomSheet title={t('installments.edit.title')} onClose={onClose} full>
      {people.data === undefined && people.isError ? (
        <LoadFailure what={t('installments.form.peopleWhat')} error={people.error} />
      ) : people.data === undefined ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <Skeleton className="h-11 w-full rounded-xl" />
          <Skeleton className="h-11 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      ) : (
        <>
          <DetailsForm plan={plan} people={people.data} onSaved={onClose} />
          <PlanCharges plan={plan} />
          <DeletePlan plan={plan} onDeleted={onClose} />
        </>
      )}
    </BottomSheet>
  )
}

interface DetailsFormProps {
  plan: InstallmentPlan
  people: readonly InstallmentPerson[]
  onSaved: () => void
}

function DetailsForm({ plan, people, onSaved }: DetailsFormProps) {
  const edit = useEditInstallment()
  const [form, setForm] = useState<EditForm>(() => initialEdit(plan))
  const [invalid, setInvalid] = useState<string | null>(null)
  const current =
    plan.contact_id !== null && plan.contact_name !== null
      ? { id: plan.contact_id, name: plan.contact_name }
      : null

  function change(patch: Partial<EditForm>) {
    setForm((before) => ({ ...before, ...patch }))
    setInvalid(null)
  }

  function submit() {
    const result = editBody(plan, form)
    if (result.error !== null) return setInvalid(result.error)
    if (Object.keys(result.body).length === 0) return onSaved()
    edit.mutate({ id: plan.id, body: result.body }, { onSuccess: onSaved })
  }

  return (
    <form
      data-testid="installment-edit-form"
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <Field label={t('installments.form.name')}>
        <input
          value={form.name}
          maxLength={NAME_MAX}
          onChange={(event) => change({ name: event.target.value })}
          className={FIELD}
        />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('installments.form.count')}>
          <NumberInput value={form.count} onChange={(count) => change({ count })} />
        </Field>
        <OwnerField people={ownerChoices(people, current)} value={form} onChange={change} />
      </div>
      {ownerChanged(plan, form.owner) && (
        <p data-testid="installment-owner-moves" className="text-[13px] text-ink-2">
          {t('installments.edit.ownerMoves')}
        </p>
      )}
      {invalid && <FormAlert>{invalid}</FormAlert>}
      {edit.isError && (
        <FormAlert>{t('installments.edit.saveError', { message: edit.error.message })}</FormAlert>
      )}
      <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={edit.isPending}>
        {edit.isPending ? t('installments.form.saving') : t('installments.edit.save')}
      </Button>
    </form>
  )
}
