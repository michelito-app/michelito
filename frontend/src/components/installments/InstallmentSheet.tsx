import { useId, useState, type ReactNode } from 'react'
import { FIELD, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { InstallmentDraft, InstallmentPlan, Tx } from '@/lib/api'
import { useCreateInstallment, useInstallmentDraft } from '@/lib/installmentQueries'
import {
  COUNT_MAX,
  COUNT_MIN,
  foundLine,
  initialForm,
  NAME_MAX,
  type Owner,
  type PlanForm,
  planBody,
} from '@/lib/installments'
import { formatMoney } from '@/lib/links'
import { useGroup, useSharedHome } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'

interface InstallmentSheetProps {
  tx: Tx
  onClose: () => void
  onCreated: (plan: InstallmentPlan) => void
}

/** "It is an installment…": the plan's name, how many installments, which one this charge is
 * (prefilled from the earlier identical charges) and whose it is (mine, or a group member's). */
export function InstallmentSheet({ tx, onClose, onCreated }: InstallmentSheetProps) {
  const draft = useInstallmentDraft(tx.fingerprint)
  return (
    <BottomSheet title={t('installments.form.title')} onClose={onClose}>
      {draft.isError ? (
        <LoadFailure what={t('installments.form.loadWhat')} error={draft.error} />
      ) : draft.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-11 w-full rounded-xl" />
          <Skeleton className="h-11 w-full rounded-xl" />
        </div>
      ) : (
        <DraftForm draft={draft.data} onCreated={onCreated} />
      )}
    </BottomSheet>
  )
}

function DraftForm({
  draft,
  onCreated,
}: {
  draft: InstallmentDraft
  onCreated: (plan: InstallmentPlan) => void
}) {
  const ids = useId()
  const create = useCreateInstallment()
  const [form, setForm] = useState<PlanForm>(() => initialForm(draft))
  const [invalid, setInvalid] = useState<string | null>(null)
  const found = foundLine(draft)

  function change(patch: Partial<PlanForm>) {
    setForm((current) => ({ ...current, ...patch }))
    setInvalid(null)
  }

  function submit() {
    const result = planBody(draft.fingerprint, form)
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
      <Field label={t('installments.form.name')} hint={t('installments.form.nameHint')}>
        <input
          value={form.name}
          maxLength={NAME_MAX}
          onChange={(event) => change({ name: event.target.value })}
          className={FIELD}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('installments.form.count')}>
          <NumberInput
            value={form.count}
            min={COUNT_MIN}
            max={COUNT_MAX}
            onChange={(count) => change({ count })}
          />
        </Field>
        <Field label={t('installments.form.number')}>
          <NumberInput
            value={form.number}
            min={1}
            max={COUNT_MAX}
            onChange={(number) => change({ number })}
          />
        </Field>
      </div>
      {found && (
        <p data-testid="installment-found" className="-mt-2 text-[13px] text-primary">
          {found}
        </p>
      )}
      <OwnerField ids={ids} form={form} onChange={change} />
      {invalid && (
        <p role="alert" className="text-[13px] text-up-ink">
          {invalid}
        </p>
      )}
      {create.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('installments.form.saveError', { message: create.error.message })}
        </p>
      )}
      <Button type="submit" className="h-11 rounded-xl text-sm font-semibold" disabled={create.isPending}>
        {create.isPending ? t('installments.form.saving') : t('installments.form.submit')}
      </Button>
    </form>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
      {label}
      {children}
      {hint && <span className="text-xs font-normal text-muted-foreground">{hint}</span>}
    </label>
  )
}

interface NumberInputProps {
  value: string
  min: number
  max: number
  onChange: (value: string) => void
}

function NumberInput({ value, min, max, onChange }: NumberInputProps) {
  return (
    <input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      step={1}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cn(FIELD, 'tabular-nums')}
    />
  )
}

interface OwnerFieldProps {
  ids: string
  form: PlanForm
  onChange: (patch: Partial<PlanForm>) => void
}

/** "Whose is it?": mine, or a member of a shared group (the group, then the person). */
function OwnerField({ ids, form, onChange }: OwnerFieldProps) {
  const options: { value: Owner; label: string; hint: string }[] = [
    { value: 'me', label: t('installments.form.mine'), hint: t('installments.form.mineHint') },
    {
      value: 'member',
      label: t('installments.form.member'),
      hint: t('installments.form.memberHint'),
    },
  ]
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="pb-2 text-[13px] font-semibold text-ink-2">
        {t('installments.form.owner')}
      </legend>
      {options.map((option) => (
        <label
          key={option.value}
          className={cn(
            'flex min-h-11 cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 text-sm transition-colors',
            form.owner === option.value
              ? 'border-primary bg-[#F6FAF8]'
              : 'border-border hover:bg-[#FAFAF8]',
          )}
        >
          <input
            type="radio"
            name={`${ids}-owner`}
            value={option.value}
            checked={form.owner === option.value}
            onChange={() => onChange({ owner: option.value })}
            className="mt-0.5 size-[18px] shrink-0 cursor-pointer accent-primary"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-semibold">{option.label}</span>
            <span className="text-[13px] text-muted-foreground">{option.hint}</span>
          </span>
        </label>
      ))}
      {form.owner === 'member' && <MemberPicker form={form} onChange={onChange} />}
    </fieldset>
  )
}

function MemberPicker({ form, onChange }: Omit<OwnerFieldProps, 'ids'>) {
  const home = useSharedHome()
  const groups = (home.data?.groups ?? []).filter((group) => !group.archived)
  const group = useGroup(form.groupId)
  const members = (group.data?.id === form.groupId ? (group.data?.members ?? []) : []).filter(
    (member) => !member.is_me,
  )
  if (home.isError) return <LoadFailure what={t('installments.form.group')} error={home.error} />
  if (home.isSuccess && groups.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{t('installments.form.noGroups')}</p>
  }
  return (
    <div className="grid gap-3 pl-1 sm:grid-cols-2">
      <Field label={t('installments.form.group')}>
        <select
          value={form.groupId ?? ''}
          onChange={(event) =>
            onChange({
              groupId: event.target.value === '' ? null : Number(event.target.value),
              contactId: null,
            })
          }
          className={cn(FIELD, 'cursor-pointer font-medium')}
        >
          <option value="">—</option>
          {groups.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t('installments.form.person')}>
        <select
          value={form.contactId ?? ''}
          disabled={form.groupId === null || members.length === 0}
          onChange={(event) =>
            onChange({ contactId: event.target.value === '' ? null : Number(event.target.value) })
          }
          className={cn(FIELD, 'cursor-pointer font-medium disabled:cursor-not-allowed disabled:opacity-60')}
        >
          <option value="">{t('installments.form.pickPerson')}</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name}
            </option>
          ))}
        </select>
      </Field>
      {group.isSuccess && members.length === 0 && (
        <p className="text-[13px] text-muted-foreground sm:col-span-2">
          {t('installments.form.noMembers')}
        </p>
      )}
    </div>
  )
}
