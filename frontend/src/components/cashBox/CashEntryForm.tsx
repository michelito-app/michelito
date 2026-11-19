import { useState } from 'react'
import { Action, FIELD, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { CashBox, CashCurrency, CashEntryKind, CashLine, Category } from '@/lib/api'
import {
  balanceAfter,
  draftDelta,
  draftOfLine,
  emptyDraft,
  ENTRY_TITLES,
  entryBody,
  type EntryDraft,
  FIRST_DAY,
  lastDay,
  wouldBeNegative,
} from '@/lib/cashBox'
import { choosable } from '@/lib/categories'
import { useCategories, useChangeCashBox } from '@/lib/queries'

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
  onDone: () => void
}

/** Write (or edit) an initial balance, money in or money out of the box. A negative balance is
 * warned about before saving, but not blocked. */
export function CashEntryForm({ kind, box, today, editing = null, onDone }: CashEntryFormProps) {
  const categories = useCategories()
  const change = useChangeCashBox()
  const [draft, setDraft] = useState<EntryDraft>(() =>
    editing ? draftOfLine(editing) : emptyDraft(kind, today),
  )
  const [error, setError] = useState<string | null>(null)
  const options = categoryOptions(categories.data ?? [], kind)
  const fallback = options.find((c) => c.builtin_key === DEFAULT_KEY[kind]) ?? options[0]
  const body = entryBody(draft, today)
  const after =
    typeof body === 'string' ? null : balanceAfter(box, body.currency, draftDelta(body, editing))

  function patch(next: Partial<EntryDraft>) {
    setDraft((current) => ({ ...current, ...next }))
    setError(null)
    change.reset()
  }

  function save() {
    if (typeof body === 'string') {
      setError(body)
      return
    }
    const withCategory =
      kind === 'initial' ? body : { ...body, category_id: draft.categoryId ?? fallback?.id ?? null }
    const request = editing?.entry_id
      ? ({ action: 'update', id: editing.entry_id, body: withoutKind(withCategory) } as const)
      : ({ action: 'add', body: withCategory } as const)
    change.mutate(request, { onSuccess: onDone })
  }

  const title = editing
    ? t('cashBox.form.editTitle', { title: ENTRY_TITLES[kind].toLowerCase() })
    : ENTRY_TITLES[kind]
  return (
    <section
      aria-label={title}
      className="flex flex-col gap-3 rounded-xl border border-border px-3.5 py-3"
    >
      <h3 className="text-sm font-semibold">{title}</h3>
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
        <label className={LABEL}>
          {t('cashBox.form.day')}
          <input
            type="date"
            min={FIRST_DAY}
            max={lastDay(today)}
            className={FIELD}
            value={draft.day}
            onChange={(event) => patch({ day: event.target.value })}
          />
        </label>
        {kind !== 'initial' && (
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
      {kind !== 'initial' && (
        <label className={LABEL}>
          {kind === 'income' ? t('cashBox.form.noteIncome') : t('cashBox.form.note')}
          <input
            className={FIELD}
            maxLength={500}
            value={draft.note}
            onChange={(event) => patch({ note: event.target.value })}
          />
        </label>
      )}
      {after !== null && typeof body !== 'string' && (
        <p
          data-testid="cash-box-would-be-negative"
          className="rounded-lg bg-up-soft px-3 py-2 text-[13px] text-up-ink"
        >
          {wouldBeNegative(body.currency, after)}
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

function categoryOptions(categories: readonly Category[], kind: CashEntryKind): Category[] {
  if (kind === 'initial') return []
  return choosable(categories).filter((c) => c.kind === WANTED_KIND[kind] && !c.hidden)
}

function withoutKind<T extends { kind: CashEntryKind }>(body: T): Omit<T, 'kind'> {
  const { kind: _kind, ...rest } = body
  return rest
}
