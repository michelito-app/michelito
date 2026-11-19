import { useState } from 'react'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { t } from '@/i18n'
import {
  asideNotes,
  type Budget,
  type BudgetLine,
  barShare,
  capInput,
  FILTERED_NOTE,
  missingText,
  parseDopAmount,
  spentText,
  warningText,
} from '@/lib/budget'
import { useActivateBudget, useResolveWarning, useSetCap } from '@/lib/budgetQueries'
import { formatDop } from '@/lib/money'
import { cn } from '@/lib/utils'

const BUTTON = cn(
  'inline-flex h-11 shrink-0 items-center justify-center rounded-xl px-4 text-sm font-semibold',
  FOCUS,
)
const PRIMARY = cn(
  BUTTON,
  'bg-primary text-primary-foreground hover:bg-primary/85 disabled:opacity-50',
)
const SECONDARY = cn(
  BUTTON,
  'border border-border bg-card text-ink-2 hover:bg-muted disabled:opacity-50',
)

/** "Categories": one bar per category (spent / cap), the one most over first, with the cap
 * editable inline, one-off expenses and what is covered apart, and the "the usual changed"
 * warnings. Not activated, it offers to activate it. */
export function CategoryBudget({ budget }: { budget: Budget }) {
  if (!budget.active) return <Activate />
  const missing = missingText(budget.missing)
  const shown = budget.lines.filter((line) => line.active)
  const rest = budget.lines.filter((line) => !line.active)
  return (
    <section
      aria-labelledby="budget-categories"
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="budget-categories" className={PANEL_TITLE}>
          {t('budget.categories.title')}
        </h2>
        <p className="text-[13px] text-ink-2">
          {t('budget.categories.total', {
            spent: formatDop(budget.spent_cents),
            cap: formatDop(budget.cap_cents),
          })}
          {budget.over_count > 0 &&
            t('budget.categories.over', {
              count: budget.over_count,
              amount: formatDop(budget.over_cents),
            })}
        </p>
      </div>
      <p className="text-[13px] text-muted-foreground">{t('budget.categories.help')}</p>
      {budget.filtered && (
        <p data-testid="budget-filtered" className="text-[13px] font-semibold text-ink-2">
          {FILTERED_NOTE}
        </p>
      )}
      {missing && (
        <p role="status" data-testid="budget-partial" className="text-[13px] font-semibold text-up-ink">
          {missing}
        </p>
      )}
      <ul className="flex flex-col">
        {shown.map((line) => (
          <CategoryRow key={line.category_id} line={line} />
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="group">
          <summary
            className={cn(
              'flex min-h-11 cursor-pointer items-center text-[13px] font-semibold text-primary',
              FOCUS,
            )}
          >
            {t('budget.categories.rest', { count: rest.length })}
          </summary>
          <ul className="flex flex-col">
            {rest.map((line) => (
              <CategoryRow key={line.category_id} line={line} />
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function Activate() {
  const activate = useActivateBudget()
  return (
    <section
      aria-labelledby="budget-categories"
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <h2 id="budget-categories" className={PANEL_TITLE}>
        {t('budget.categories.title')}
      </h2>
      <p className="text-sm text-ink-2">{t('budget.activate.help')}</p>
      <div>
        <button
          type="button"
          className={PRIMARY}
          disabled={activate.isPending}
          onClick={() => activate.mutate()}
        >
          {activate.isPending ? t('budget.activate.pending') : t('budget.activate.button')}
        </button>
      </div>
      {activate.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('budget.activate.error', { message: activate.error.message })}
        </p>
      )}
    </section>
  )
}

function CategoryRow({ line }: { line: BudgetLine }) {
  const [editing, setEditing] = useState(false)
  const { share } = barShare(line)
  const over = line.passed
  const notes = asideNotes(line)
  return (
    <li
      aria-label={line.category}
      data-testid="budget-line"
      className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 text-sm font-semibold">{line.category}</span>
        <span className={cn('text-sm tabular-nums', over ? 'font-semibold text-up' : 'text-ink-2')}>
          {spentText(line).replace(/RD\$ /g, 'RD$\u00a0')}
          {line.over_cents > 0 && t('budget.line.overBy', { amount: formatDop(line.over_cents) })}
        </span>
      </div>
      {line.cap_cents !== null && (
        <div
          role="meter"
          aria-label={t('budget.line.meter', { category: line.category })}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={share}
          className="h-2 overflow-hidden rounded-full bg-muted"
        >
          <div
            className={cn('h-full rounded-full', over ? 'bg-up' : 'bg-primary')}
            style={{ width: `${share}%` }}
          />
        </div>
      )}
      {notes.length > 0 && <p className="text-[13px] text-ink-2">{notes.join(' · ')}</p>}
      {line.warning && <WarningBox line={line} />}
      {editing ? (
        <CapEditor line={line} onClose={() => setEditing(false)} />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={SECONDARY}
            aria-label={t('budget.line.editLabel', { category: line.category })}
            onClick={() => setEditing(true)}
          >
            {line.cap_cents === null ? t('budget.line.setCap') : t('budget.line.editCap')}
          </button>
          {line.manual && (
            <span className="text-[13px] text-muted-foreground">{t('budget.line.manual')}</span>
          )}
        </div>
      )}
    </li>
  )
}

function CapEditor({ line, onClose }: { line: BudgetLine; onClose: () => void }) {
  const [text, setText] = useState(capInput(line.cap_cents))
  const [invalid, setInvalid] = useState(false)
  const save = useSetCap()
  const submit = (cents: number | null) =>
    save.mutate({ categoryId: line.category_id, cents }, { onSuccess: onClose })
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        const cents = parseDopAmount(text)
        if (cents === null) {
          setInvalid(true)
          return
        }
        submit(cents)
      }}
    >
      <input
        type="text"
        inputMode="decimal"
        aria-label={t('budget.cap.inputLabel', { category: line.category })}
        aria-invalid={invalid}
        value={text}
        onChange={(event) => {
          setText(event.target.value)
          setInvalid(false)
        }}
        className={cn(
          'h-11 w-32 min-w-0 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm',
          FOCUS,
        )}
      />
      <button type="submit" className={PRIMARY} disabled={save.isPending}>
        {t('budget.cap.save')}
      </button>
      <button
        type="button"
        className={SECONDARY}
        disabled={save.isPending}
        onClick={() => submit(null)}
      >
        {t('budget.cap.none')}
      </button>
      <button type="button" className={SECONDARY} onClick={onClose}>
        {t('budget.cancel')}
      </button>
      {invalid && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('budget.cap.invalid')}
        </p>
      )}
      {save.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          {t('budget.saveError', { message: save.error.message })}
        </p>
      )}
    </form>
  )
}

function WarningBox({ line }: { line: BudgetLine }) {
  const resolve = useResolveWarning()
  const decide = (accept: boolean) => resolve.mutate({ categoryId: line.category_id, accept })
  return (
    <div
      role="group"
      aria-label={t('budget.warning.label', { category: line.category })}
      className="flex flex-col gap-2 rounded-xl border border-up/30 bg-up-soft px-3 py-2"
    >
      <p className="text-[13px] text-up-ink">{warningText(line).replace(/RD\$ /g, 'RD$\u00a0')}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={PRIMARY}
          disabled={resolve.isPending}
          onClick={() => decide(true)}
        >
          {t('budget.warning.accept')}
        </button>
        <button
          type="button"
          className={SECONDARY}
          disabled={resolve.isPending}
          onClick={() => decide(false)}
        >
          {t('budget.warning.keep')}
        </button>
      </div>
      {resolve.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('budget.saveError', { message: resolve.error.message })}
        </p>
      )}
    </div>
  )
}
