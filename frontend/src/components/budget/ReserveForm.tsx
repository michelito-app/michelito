import { useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Category } from '@/lib/api'
import {
  type Reserve,
  type ReserveBody,
  type Schedule,
  SCHEDULES,
  parseDopAmount,
  scheduleMonths,
  scheduleOf,
} from '@/lib/budget'
import { choosable } from '@/lib/categories'
import { cn } from '@/lib/utils'

const FIELD = cn(
  'h-11 w-full min-w-0 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm text-foreground',
  FOCUS,
)
const LABEL = 'flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2'
const BUTTON = cn(
  'inline-flex h-11 items-center justify-center rounded-xl px-4 text-sm font-semibold',
  FOCUS,
)

interface ReserveFormProps {
  categories: readonly Category[]
  /** To edit: the current reserve (otherwise, a new one). */
  current?: Reserve
  /** This month (YYYY-MM), for the default due date. */
  today: string
  busy: boolean
  error: string | null
  onSave: (body: ReserveBody) => void
  onCancel: () => void
}

/** Name, estimated amount (RD$), category, how often (every year, every 6 months or once), the
 * due date (YYYY-MM) and whether it gathers several expenses. */
export function ReserveForm({
  categories,
  current,
  today,
  busy,
  error,
  onSave,
  onCancel,
}: ReserveFormProps) {
  const usable = choosable(categories.filter((c) => c.kind === 'expense' && !c.hidden))
  const [name, setName] = useState(current?.name ?? '')
  const [amount, setAmount] = useState(current ? String(current.amount_cents / 100) : '')
  const [categoryId, setCategoryId] = useState(String(current?.category_id ?? usable[0]?.id ?? ''))
  const [schedule, setSchedule] = useState<Schedule>(scheduleOf(current?.every_months ?? 12))
  const [due, setDue] = useState(current?.due_month ?? today)
  const [multiple, setMultiple] = useState(current?.multiple ?? false)
  const [problem, setProblem] = useState<string | null>(null)

  function submit() {
    const cents = parseDopAmount(amount)
    if (!name.trim()) return setProblem(t('budget.form.nameMissing'))
    if (cents === null || cents <= 0) return setProblem(t('budget.form.amountInvalid'))
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(due)) return setProblem(t('budget.form.dueMissing'))
    setProblem(null)
    onSave({
      name: name.trim(),
      amount_cents: cents,
      category_id: Number(categoryId),
      due_month: due,
      every_months: scheduleMonths(schedule),
      multiple,
    })
  }

  return (
    <form
      aria-label={current ? t('budget.form.editLabel', { name: current.name }) : t('budget.form.newLabel')}
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <label className={LABEL}>
        {t('budget.form.name')}
        <input
          aria-label={t('budget.form.nameLabel')}
          value={name}
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
          className={FIELD}
        />
      </label>
      <label className={LABEL}>
        {t('budget.form.amount')}
        <input
          aria-label={t('budget.form.amount')}
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          className={FIELD}
        />
      </label>
      <label className={LABEL}>
        {t('budget.form.category')}
        <select
          aria-label={t('budget.form.categoryLabel')}
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
          className={cn(FIELD, 'cursor-pointer')}
        >
          {usable.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label className={LABEL}>
        {schedule === 'once' ? t('budget.form.dueOnce') : t('budget.form.dueFirst')}
        <input
          type="month"
          aria-label={t('budget.form.dueLabel')}
          value={due}
          onChange={(event) => setDue(event.target.value)}
          className={FIELD}
        />
      </label>
      <fieldset className="flex flex-wrap gap-2 sm:col-span-2">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">
          {t('budget.form.schedule')}
        </legend>
        {SCHEDULES.map((option) => (
          <label
            key={option.value}
            className={cn(
              'flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm',
              schedule === option.value ? 'border-primary bg-[#F6FAF8]' : 'border-border',
            )}
          >
            <input
              type="radio"
              name="reserve-schedule"
              checked={schedule === option.value}
              onChange={() => setSchedule(option.value)}
              className="size-[18px] cursor-pointer accent-primary"
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          checked={multiple}
          onChange={(event) => setMultiple(event.target.checked)}
          className="size-[18px] cursor-pointer accent-primary"
        />
        {t('budget.form.multiple')}
      </label>
      {(problem || error) && (
        <p role="alert" className="text-[13px] text-up-ink sm:col-span-2">
          {problem ?? t('budget.saveError', { message: error ?? '' })}
        </p>
      )}
      <div className="flex flex-wrap gap-2 sm:col-span-2">
        <button
          type="submit"
          disabled={busy}
          className={cn(BUTTON, 'bg-primary text-primary-foreground hover:bg-primary/85 disabled:opacity-50')}
        >
          {current ? t('budget.form.saveChanges') : t('budget.form.create')}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className={cn(BUTTON, 'border border-border bg-card text-ink-2 hover:bg-muted')}
        >
          {t('budget.cancel')}
        </button>
      </div>
    </form>
  )
}
