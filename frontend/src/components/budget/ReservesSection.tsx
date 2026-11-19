import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { t } from '@/i18n'
import { type Selection, transactionsHref } from '@/lib/accountFilter'
import type { Category } from '@/lib/api'
import {
  bodyFromSuggestion,
  dueText,
  type Reserve,
  type ReserveBody,
  type Reserves,
  type ReserveSuggestion,
  scheduleText,
  suggestionText,
  yearText,
} from '@/lib/budget'
import { useChangeReserve } from '@/lib/budgetQueries'
import { formatDop, formatUsd } from '@/lib/money'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'
import { ReserveForm } from './ReserveForm'

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

interface ReservesSectionProps {
  data: Reserves
  categories: readonly Category[]
  today: string
  selection: Selection
}

/** "Reserves": what to set aside each month for the expenses that are not monthly (without
 * moving money), with the next due date, the contribution, this year and the linked expenses;
 * create, edit and delete, and the pending suggestions. */
export function ReservesSection({ data, categories, today, selection }: ReservesSectionProps) {
  const [creating, setCreating] = useState(false)
  const change = useChangeReserve()
  const save = (body: ReserveBody) =>
    change.mutate({ action: 'create', body }, { onSuccess: () => setCreating(false) })
  return (
    <section
      aria-labelledby="budget-reserves"
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="budget-reserves" className={PANEL_TITLE}>
          {t('budget.reserves.title')}
        </h2>
        {data.items.length > 0 && (
          <p className="text-[13px] text-ink-2">
            {t('budget.reserves.monthly', { amount: formatDop(data.monthly_cents) })}
          </p>
        )}
      </div>
      <p className="text-[13px] text-muted-foreground">{t('budget.reserves.help')}</p>
      {data.suggestions.length > 0 && <Suggestions items={data.suggestions} />}
      {data.items.length > 0 ? (
        <ul className="flex flex-col">
          {data.items.map((reserve) => (
            <ReserveRow
              key={reserve.id}
              reserve={reserve}
              categories={categories}
              today={today}
              selection={selection}
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-ink-2">{t('budget.reserves.none')}</p>
      )}
      {creating ? (
        <ReserveForm
          categories={categories}
          today={today}
          busy={change.isPending}
          error={change.isError ? change.error.message : null}
          onSave={save}
          onCancel={() => setCreating(false)}
        />
      ) : (
        <div>
          <button type="button" className={SECONDARY} onClick={() => setCreating(true)}>
            {t('budget.reserves.new')}
          </button>
        </div>
      )}
    </section>
  )
}

function Suggestions({ items }: { items: ReserveSuggestion[] }) {
  const change = useChangeReserve()
  return (
    <div role="group" aria-label={t('budget.suggestions.label')} className="flex flex-col gap-2">
      <h3 className="text-[13px] font-semibold text-ink-2">{t('budget.suggestions.title')}</h3>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li
            key={item.key}
            aria-label={item.name}
            className="flex flex-col gap-2 rounded-xl border border-primary/30 bg-[#F6FAF8] px-3 py-2"
          >
            <p className="text-sm text-foreground">
              {suggestionText(item).replace(/RD\$ /g, 'RD$\u00a0')}
            </p>
            <p className="text-[13px] text-muted-foreground">{item.reason}</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={PRIMARY}
                aria-label={t('budget.suggestions.createLabel', { name: item.name })}
                disabled={change.isPending}
                onClick={() => change.mutate({ action: 'create', body: bodyFromSuggestion(item) })}
              >
                {t('budget.form.create')}
              </button>
              <button
                type="button"
                className={SECONDARY}
                aria-label={t('budget.suggestions.dismissLabel', { name: item.name })}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({ action: 'dismiss', key: item.key, name: item.name })
                }
              >
                {t('budget.suggestions.dismiss')}
              </button>
            </div>
          </li>
        ))}
      </ul>
      {change.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('budget.saveError', { message: change.error.message })}
        </p>
      )}
    </div>
  )
}

interface ReserveRowProps {
  reserve: Reserve
  categories: readonly Category[]
  today: string
  selection: Selection
}

function ReserveRow({ reserve, categories, today, selection }: ReserveRowProps) {
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const change = useChangeReserve()
  const update = (body: ReserveBody) =>
    change.mutate(
      { action: 'update', id: reserve.id, body: { ...body, once: body.every_months === null } },
      { onSuccess: () => setEditing(false) },
    )
  return (
    <li aria-label={reserve.name} className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 text-sm font-semibold">{reserve.name}</span>
        <span className="text-sm font-semibold tabular-nums">
          {t('budget.reserve.perMonth', { amount: formatDop(reserve.monthly_cents) })}
        </span>
      </div>
      <p className="text-[13px] text-ink-2">
        {formatDop(reserve.amount_cents)} · {scheduleText(reserve)} · {reserve.category}
        {reserve.multiple && t('budget.reserve.multiple')}
      </p>
      <p className="text-[13px] text-ink-2">
        {dueText(reserve)}
        {reserve.paid && t('budget.reserve.paid')} · {yearText(reserve)}
        {reserve.year_without_rate > 0 &&
          t('budget.reserve.yearWithoutRate', { count: reserve.year_without_rate })}
      </p>
      {reserve.members.length > 0 && (
        <ul
          aria-label={t('budget.reserve.membersLabel', { name: reserve.name })}
          className="flex flex-col gap-1 pl-3"
        >
          {reserve.members.map((member) => (
            <li key={member.fingerprint} className="flex flex-wrap items-center gap-x-2 text-[13px]">
              <Link
                to={transactionsHref({ month: member.month, tx: member.fingerprint }, selection)}
                className="font-semibold text-primary"
              >
                {member.merchant}
              </Link>
              <span className="text-muted-foreground">
                {t('budget.reserve.memberLine', {
                  day: shortDay(member.day),
                  amount:
                    member.currency === 'USD'
                      ? formatUsd(member.amount_cents)
                      : formatDop(member.amount_cents),
                })}
              </span>
              <button
                type="button"
                className={cn('min-h-11 rounded-md px-2 font-semibold text-ink-2 hover:bg-muted', FOCUS)}
                aria-label={t('budget.reserve.unlinkLabel', { merchant: member.merchant })}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({
                    action: 'unlink',
                    id: reserve.id,
                    fingerprint: member.fingerprint,
                  })
                }
              >
                {t('budget.reserve.unlink')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <ReserveForm
          categories={categories}
          current={reserve}
          today={today}
          busy={change.isPending}
          error={change.isError ? change.error.message : null}
          onSave={update}
          onCancel={() => setEditing(false)}
        />
      ) : confirming ? (
        <div
          role="alertdialog"
          aria-label={t('budget.reserve.deleteLabel', { name: reserve.name })}
          className="flex flex-wrap items-center gap-2"
        >
          <span className="text-[13px] text-ink-2">{t('budget.reserve.deleteConfirm')}</span>
          <button
            type="button"
            className={PRIMARY}
            disabled={change.isPending}
            onClick={() => change.mutate({ action: 'delete', id: reserve.id })}
          >
            {t('budget.reserve.deleteYes')}
          </button>
          <button type="button" className={SECONDARY} onClick={() => setConfirming(false)}>
            {t('budget.cancel')}
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={SECONDARY}
            aria-label={t('budget.form.editLabel', { name: reserve.name })}
            onClick={() => setEditing(true)}
          >
            {t('budget.reserve.edit')}
          </button>
          <button
            type="button"
            className={SECONDARY}
            aria-label={t('budget.reserve.deleteLabel', { name: reserve.name })}
            onClick={() => setConfirming(true)}
          >
            {t('budget.reserve.delete')}
          </button>
        </div>
      )}
      {change.isError && !editing && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('budget.saveError', { message: change.error.message })}
        </p>
      )}
    </li>
  )
}
