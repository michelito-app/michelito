import { useId, useState } from 'react'
import { Action, FIELD, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type {
  CashBox,
  CashCurrency,
  CashEntryBody,
  CashEntryKind,
  CashLine,
  CashSchedule,
  Category,
  Frequency,
} from '@/lib/api'
import {
  balanceAfter,
  CONCEPT_MAX,
  draftDelta,
  draftOfLine,
  draftOfSchedule,
  emptyDraft,
  type EndMode,
  ENTRY_TITLES,
  entryBody,
  type EntryDraft,
  FIRST_DAY,
  FREQUENCIES,
  FREQUENCY_LABELS,
  knownConcept,
  lastDay,
  matchConcepts,
  MAX_TIMES,
  scheduleBody,
  wouldBeNegative,
} from '@/lib/cashBox'
import { choosable } from '@/lib/categories'
import {
  type CashBoxChange,
  useCashConcepts,
  useCategories,
  useChangeCashBox,
} from '@/lib/queries'
import { cn } from '@/lib/utils'

/** The category proposed unless another is chosen (the same the server sets). */
const DEFAULT_KEY: Record<CashEntryKind, string | null> = {
  initial: null,
  income: 'OTHER_INCOME',
  expense: 'CASH',
}
const WANTED_KIND = { income: 'income', expense: 'expense' } as const
const LABEL = 'flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2'

interface CashEntryFormProps {
  kind: CashEntryKind
  box: CashBox
  /** Today ("YYYY-MM-DD", local time): default date and end of the range. */
  today: string
  /** The line being edited (null: a new one). */
  editing?: CashLine | null
  /** A schedule form ("Schedule a payment or collection"), new or this one to edit. */
  schedule?: CashSchedule | 'new' | null
  /** The "I spent cash / I received cash" switch (the quick «+»). */
  switchable?: boolean
  /** Without the title (inside a sheet that already has one). */
  untitled?: boolean
  onDone: () => void
}

/** Write (or edit) an initial balance, money in or money out of cash, or a scheduled payment
 * or collection. A new income or expense needs its concept; picking one written before brings
 * its last category and currency. "Repeat" turns a new one into a schedule from its date. A
 * negative balance is warned about before saving, but not blocked. */
export function CashEntryForm({
  kind,
  box,
  today,
  editing = null,
  schedule = null,
  switchable = false,
  untitled = false,
  onDone,
}: CashEntryFormProps) {
  const categories = useCategories()
  const change = useChangeCashBox()
  const concepts = useCashConcepts(kind !== 'initial')
  const listId = useId()
  const [draft, setDraft] = useState<EntryDraft>(() => {
    if (schedule && schedule !== 'new') return draftOfSchedule(schedule)
    if (editing) return draftOfLine(editing)
    return { ...emptyDraft(kind, today), repeat: schedule === 'new' }
  })
  const [error, setError] = useState<string | null>(null)
  const scheduling = schedule !== null
  const current = draft.kind
  const options = categoryOptions(categories.data ?? [], current)
  const fallback = options.find((c) => c.builtin_key === DEFAULT_KEY[current]) ?? options[0]
  const planned = scheduling ? scheduleBody(draft) : null
  const entry = scheduling ? null : entryBody(draft, today, editing !== null)
  // The balance warning only needs the amount and currency: it shows before the concept is in.
  const preview = scheduling
    ? null
    : entryBody({ ...draft, concept: draft.concept || '-', repeat: false }, today, true)
  const after =
    preview === null || typeof preview === 'string'
      ? null
      : balanceAfter(box, preview.currency, draftDelta(preview, editing))
  const suggestions = matchConcepts(concepts.data ?? [], current, draft.concept).slice(0, 12)

  function patch(next: Partial<EntryDraft>) {
    setDraft((now) => ({ ...now, ...next }))
    setError(null)
    change.reset()
  }

  function typeConcept(text: string) {
    const known = knownConcept(concepts.data ?? [], current, text)
    if (known && !editing && !(schedule && schedule !== 'new')) {
      patch({ concept: text, categoryId: known.category_id, currency: known.currency })
    } else {
      patch({ concept: text })
    }
  }

  function save() {
    const categoryId = draft.categoryId ?? fallback?.id ?? null
    if (planned !== null) {
      if (typeof planned === 'string') {
        setError(planned)
        return
      }
      const withCategory = { ...planned, category_id: categoryId }
      const request: CashBoxChange =
        schedule !== 'new' && schedule !== null
          ? { action: 'schedule-update', id: schedule.id, body: withCategory }
          : { action: 'schedule-add', body: withCategory }
      change.mutate(request, { onSuccess: onDone })
      return
    }
    if (entry === null) return
    if (typeof entry === 'string') {
      setError(entry)
      return
    }
    const withCategory = current === 'initial' ? entry : { ...entry, category_id: categoryId }
    const request: CashBoxChange = editing?.entry_id
      ? { action: 'update', id: editing.entry_id, body: withoutKind(withCategory) }
      : { action: 'add', body: withCategory }
    change.mutate(request, { onSuccess: onDone })
  }

  const title = formTitle(current, editing, schedule)
  const showRepeat = !editing && !scheduling && current !== 'initial'
  return (
    <section
      aria-label={title}
      className="flex flex-col gap-3 rounded-xl border border-border px-3.5 py-3"
    >
      {!untitled && <h3 className="text-sm font-semibold">{title}</h3>}
      {(switchable || schedule === 'new') && (
        <KindSwitch
          scheduling={scheduling}
          value={current === 'income' ? 'income' : 'expense'}
          onChange={(next) => patch({ kind: next, categoryId: null })}
        />
      )}
      <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
        <label className={LABEL}>
          {t('cashBox.form.amount')}
          <input
            className={FIELD}
            inputMode="decimal"
            autoComplete="off"
            value={draft.amount}
            placeholder="0.00"
            onChange={(event) => patch({ amount: event.target.value })}
          />
        </label>
        <label className={LABEL}>
          {t('cashBox.form.currency')}
          <select
            className={FIELD}
            aria-label={t('cashBox.form.currency')}
            value={draft.currency}
            onChange={(event) => patch({ currency: event.target.value as CashCurrency })}
          >
            <option value="DOP">RD$</option>
            <option value="USD">US$</option>
          </select>
        </label>
        {current !== 'initial' && (
          <label className={cn(LABEL, 'min-[420px]:col-span-2')}>
            {t('cashBox.form.concept')}
            <input
              className={FIELD}
              list={listId}
              autoComplete="off"
              maxLength={CONCEPT_MAX * 2}
              placeholder={t('cashBox.form.conceptHint')}
              value={draft.concept}
              onChange={(event) => typeConcept(event.target.value)}
            />
            <datalist id={listId}>
              {suggestions.map((item) => (
                <option key={`${item.kind}-${item.concept}`} value={item.concept} />
              ))}
            </datalist>
          </label>
        )}
        <label className={LABEL}>
          {scheduling ? t('cashBox.schedule.start') : t('cashBox.form.day')}
          <input
            type="date"
            min={FIRST_DAY}
            max={scheduling ? undefined : lastDay(today)}
            className={FIELD}
            value={draft.day}
            onChange={(event) => patch({ day: event.target.value })}
          />
        </label>
        {current !== 'initial' && (
          <label className={LABEL}>
            {t('cashBox.form.category')}
            <select
              className={FIELD}
              aria-label={t('cashBox.form.category')}
              value={draft.categoryId ?? fallback?.id ?? ''}
              onChange={(event) => patch({ categoryId: Number(event.target.value) })}
            >
              {options.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {current !== 'initial' && !scheduling && (
        <label className={LABEL}>
          {current === 'income' ? t('cashBox.form.noteIncome') : t('cashBox.form.note')}
          <input
            className={FIELD}
            maxLength={500}
            value={draft.note}
            onChange={(event) => patch({ note: event.target.value })}
          />
        </label>
      )}
      {showRepeat && (
        <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
          <input
            type="checkbox"
            className="size-5 accent-[var(--color-primary)]"
            checked={draft.repeat}
            onChange={(event) => patch({ repeat: event.target.checked })}
          />
          {t('cashBox.form.repeat')}
        </label>
      )}
      {(scheduling || (showRepeat && draft.repeat)) && (
        <RepeatFields draft={draft} patch={patch} />
      )}
      {scheduling && schedule !== 'new' && (
        <p className="text-[13px] text-muted-foreground">{t('cashBox.schedule.amountNote')}</p>
      )}
      {after !== null && (
        <p
          data-testid="cash-box-would-be-negative"
          className="rounded-lg bg-up-soft px-3 py-2 text-[13px] text-up-ink"
        >
          {wouldBeNegative(draft.currency, after)}
        </p>
      )}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {error}
        </p>
      )}
      <Failure error={change.error} />
      <div className="flex flex-wrap gap-2">
        <Action primary disabled={change.isPending} onClick={save}>
          {change.isPending ? t('cashBox.form.saving') : t('cashBox.form.save')}
        </Action>
        <Action onClick={onDone}>{t('cashBox.form.cancel')}</Action>
      </div>
    </section>
  )
}

function formTitle(
  kind: CashEntryKind,
  editing: CashLine | null,
  schedule: CashSchedule | 'new' | null,
): string {
  if (schedule === 'new') return t('cashBox.schedule.formTitle')
  if (schedule) return t('cashBox.schedule.editTitle', { concept: schedule.concept })
  if (editing) return t('cashBox.form.editTitle', { title: ENTRY_TITLES[kind].toLowerCase() })
  return ENTRY_TITLES[kind]
}

interface KindSwitchProps {
  scheduling: boolean
  value: 'income' | 'expense'
  onChange: (kind: 'income' | 'expense') => void
}

/** "I spent cash / I received cash" (or "Payment / Collection" for a schedule). */
function KindSwitch({ scheduling, value, onChange }: KindSwitchProps) {
  const labels = scheduling
    ? { expense: t('cashBox.schedule.payment'), income: t('cashBox.schedule.collection') }
    : { expense: t('cashBox.kind.expense'), income: t('cashBox.kind.income') }
  return (
    <div
      role="radiogroup"
      aria-label={scheduling ? t('cashBox.schedule.kindLabel') : t('cashBox.kind.label')}
      className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1"
    >
      {(['expense', 'income'] as const).map((kind) => (
        <button
          key={kind}
          type="button"
          role="radio"
          aria-checked={value === kind}
          onClick={() => onChange(kind)}
          className={cn(
            'min-h-11 rounded-lg px-3 text-sm font-semibold',
            value === kind ? 'bg-card text-foreground shadow-sm' : 'text-ink-2',
          )}
        >
          {labels[kind]}
        </button>
      ))}
    </div>
  )
}

interface RepeatFieldsProps {
  draft: EntryDraft
  patch: (next: Partial<EntryDraft>) => void
}

function RepeatFields({ draft, patch }: RepeatFieldsProps) {
  return (
    <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
      <label className={LABEL}>
        {t('cashBox.form.frequency')}
        <select
          className={FIELD}
          aria-label={t('cashBox.form.frequency')}
          value={draft.frequency}
          onChange={(event) => patch({ frequency: event.target.value as Frequency })}
        >
          {FREQUENCIES.map((frequency) => (
            <option key={frequency} value={frequency}>
              {FREQUENCY_LABELS[frequency]}
            </option>
          ))}
        </select>
      </label>
      <label className={LABEL}>
        {t('cashBox.form.ends')}
        <select
          className={FIELD}
          aria-label={t('cashBox.form.ends')}
          value={draft.endMode}
          onChange={(event) => patch({ endMode: event.target.value as EndMode })}
        >
          <option value="never">{t('cashBox.form.endsNever')}</option>
          <option value="on">{t('cashBox.form.endsOn')}</option>
          <option value="after">{t('cashBox.form.endsAfter')}</option>
        </select>
      </label>
      {draft.endMode === 'on' && (
        <label className={LABEL}>
          {t('cashBox.form.endDay')}
          <input
            type="date"
            min={draft.day}
            className={FIELD}
            value={draft.endDay}
            onChange={(event) => patch({ endDay: event.target.value })}
          />
        </label>
      )}
      {draft.endMode === 'after' && (
        <label className={LABEL}>
          {t('cashBox.form.times')}
          <input
            className={FIELD}
            inputMode="numeric"
            max={MAX_TIMES}
            value={draft.times}
            onChange={(event) => patch({ times: event.target.value })}
          />
        </label>
      )}
    </div>
  )
}

function categoryOptions(categories: readonly Category[], kind: CashEntryKind): Category[] {
  if (kind === 'initial') return []
  return choosable(categories).filter((c) => c.kind === WANTED_KIND[kind] && !c.hidden)
}

function withoutKind(body: CashEntryBody): Omit<CashEntryBody, 'kind'> {
  const { kind: _kind, repeat: _repeat, ...rest } = body
  return rest
}
