import { ChevronRight, Plus } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Failure, FIELD } from '@/components/transactions/linkParts'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { LinkedTx } from '@/lib/api'
import {
  amountCents,
  defaultPayer,
  displayName,
  draftOf,
  draftShortfall,
  draftValid,
  equalDraft,
  splitFields,
  shortfallText,
  splitSummary,
  type SplitDraft,
} from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import { localToday, shortDay } from '@/lib/months'
import { useCategories } from '@/lib/queries'
import type { Entry, EntryBody, Group, GroupRow } from '@/lib/sharedApi'
import { ledger, useContacts, useGroup, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { Chip } from './parts'
import { CHIP, CHIP_OFF } from './styles'
import { SplitSheet } from './SplitSheet'

const LABEL = 'text-[13px] font-semibold text-ink-2'
const CURRENCIES = ['DOP', 'USD'] as const

interface ExpenseFormProps {
  /** "I paid it" with this bank transaction, or "someone else paid it" (no transaction). */
  tx: LinkedTx | null
  groups: readonly GroupRow[]
  groupId: number | null
  onGroup: (id: number) => void
  /** "+ New group" without losing the draft. */
  onNewGroup: () => void
  /** Editing a saved expense. */
  entry?: Entry
  onSaved: (group: Group) => void
}

/** The expense's details: the group, and for one paid by someone else the amount (big, decimal
 * keyboard), currency, description, "Paid by", date and category; then the split line that
 * opens the split sheet. */
export function ExpenseForm({ tx, groups, groupId, onGroup, onNewGroup, entry, onSaved }: ExpenseFormProps) {
  const ids = useId()
  const group = useGroup(groupId)
  const contacts = useContacts()
  const categories = useCategories()
  const write = useLedgerWrite()
  const linked = tx !== null || (entry !== undefined && entry.transaction !== null && entry.paid_by_me)
  const [amount, setAmount] = useState(entry ? (entry.amount_cents / 100).toFixed(2) : '')
  const [currency, setCurrency] = useState(entry?.currency ?? tx?.currency ?? 'DOP')
  const [description, setDescription] = useState(entry?.description ?? tx?.merchant ?? '')
  const [day, setDay] = useState(entry?.day ?? localToday())
  const [category, setCategory] = useState<string>(entry?.category_id != null ? String(entry.category_id) : '')
  const [payer, setPayer] = useState<number | null>(entry?.paid_by ?? null)
  const [draft, setDraft] = useState<{ group: number | null; draft: SplitDraft } | null>(
    entry ? { group: groupId, draft: draftOf(entry) } : null,
  )
  const [splitting, setSplitting] = useState(false)

  const members = group.data?.id === groupId ? (group.data?.members ?? []) : []
  const me = members.find((m) => m.is_me)
  const others = members.filter((m) => !m.is_me)
  const paidBy = linked
    ? (me?.id ?? null)
    : (payer !== null && others.some((m) => m.id === payer)
        ? payer
        : defaultPayer(others.map((m) => m.id), contacts.data?.recent_payers ?? []))
  const total = tx ? Math.abs(tx.amount_cents) : linked && entry ? entry.amount_cents : (amountCents(amount) ?? 0)
  const shownCurrency = tx?.currency ?? (linked && entry ? entry.currency : currency)
  const split =
    draft && draft.group === groupId ? draft.draft : equalDraft(members.map((m) => m.id))
  const ready =
    groupId !== null &&
    members.length > 0 &&
    paidBy !== null &&
    total > 0 &&
    description.trim() !== '' &&
    draftValid(split, total)

  function save() {
    if (!ready || groupId === null || paidBy === null) return
    const fields = splitFields(split)
    const body: EntryBody = tx
      ? { fingerprint: tx.fingerprint, description: description.trim(), ...fields }
      : {
          paid_by: paidBy,
          amount_cents: total,
          currency: shownCurrency,
          day,
          description: description.trim(),
          category_id: category === '' ? null : Number(category),
          ...fields,
        }
    write.mutate(
      () => (entry ? ledger.putEntry(entry.id, body) : ledger.addEntry(groupId, body)),
      { onSuccess: onSaved },
    )
  }

  const expenseCategories = (categories.data ?? [])
    .filter((c) => c.kind === 'expense' && !c.hidden)
    .sort((a, b) => a.name.localeCompare(b.name))
  const summary = splitSummary(split, total, shownCurrency, members)

  return (
    <>
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        save()
      }}
    >
      {tx && (
        <p className="rounded-xl bg-muted px-3.5 py-2.5 text-[13px] text-ink-2">
          {t('shared.add.fromBank', { merchant: tx.merchant, day: shortDay(tx.day) })} ·{' '}
          <span className="font-semibold tabular-nums">{formatMoney(total, shownCurrency)}</span>
        </p>
      )}

      {!entry && (
        <fieldset className="flex flex-col gap-2">
          <legend className={cn(LABEL, 'pb-2')}>{t('shared.add.group')}</legend>
          {groups.length === 0 && (
            <p className="text-[13px] text-muted-foreground">{t('shared.add.noGroups')}</p>
          )}
          <div className="flex flex-wrap gap-2">
            {groups.map((row) => (
              <Chip key={row.id} on={row.id === groupId} onClick={() => onGroup(row.id)}>
                {row.name}
              </Chip>
            ))}
            <button type="button" onClick={onNewGroup} className={cn(CHIP, CHIP_OFF, 'text-primary')}>
              <Plus size={16} aria-hidden="true" />
              {t('shared.add.newGroup')}
            </button>
          </div>
        </fieldset>
      )}

      {!linked && (
        <>
          <div className="flex flex-col gap-2">
            <label htmlFor={`${ids}-amount`} className={LABEL}>
              {t('shared.add.amount')}
            </label>
            <div className="flex items-center gap-2">
              <input
                id={`${ids}-amount`}
                inputMode="decimal"
                autoComplete="off"
                value={amount}
                placeholder="0"
                onChange={(event) => setAmount(event.target.value)}
                className={cn(
                  FIELD,
                  'h-16 flex-1 text-[34px] font-bold tracking-[-0.02em] tabular-nums',
                )}
              />
              <div role="group" aria-label={t('shared.add.currency')} className="flex shrink-0 gap-1">
                {CURRENCIES.map((code) => (
                  <Chip key={code} on={currency === code} onClick={() => setCurrency(code)}>
                    {code === 'DOP' ? 'RD$' : 'US$'}
                  </Chip>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      <div className="flex flex-col gap-2">
        <label htmlFor={`${ids}-description`} className={LABEL}>
          {t('shared.add.description')}
        </label>
        <input
          id={`${ids}-description`}
          value={description}
          maxLength={120}
          placeholder={t('shared.add.descriptionPlaceholder')}
          onChange={(event) => setDescription(event.target.value)}
          className={FIELD}
        />
      </div>

      {!linked && (
        <>
          <fieldset className="flex flex-col gap-2">
            <legend className={cn(LABEL, 'pb-2')}>{t('shared.add.paidBy')}</legend>
            <div className="flex flex-wrap gap-2">
              {others.map((member) => (
                <Chip key={member.id} on={member.id === paidBy} onClick={() => setPayer(member.id)}>
                  {member.name}
                </Chip>
              ))}
            </div>
          </fieldset>
          <div className="flex flex-wrap gap-4">
            <div className="flex min-w-[150px] flex-1 flex-col gap-2">
              <label htmlFor={`${ids}-day`} className={LABEL}>
                {t('shared.add.day')}
              </label>
              <input
                id={`${ids}-day`}
                type="date"
                value={day}
                required
                onChange={(event) => setDay(event.target.value)}
                className={FIELD}
              />
            </div>
            <div className="flex min-w-[150px] flex-1 flex-col gap-2">
              <label htmlFor={`${ids}-category`} className={LABEL}>
                {t('shared.add.category')}
              </label>
              <select
                id={`${ids}-category`}
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className={cn(FIELD, 'cursor-pointer')}
              >
                <option value="">{t('shared.add.noCategory')}</option>
                {expenseCategories.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </>
      )}

      <div className="flex flex-col gap-2">
        <span className={LABEL}>{t('shared.add.split')}</span>
        <button
          type="button"
          aria-haspopup="dialog"
          aria-label={t('shared.add.splitChange', { summary })}
          disabled={members.length === 0}
          onClick={() => setSplitting(true)}
          className={cn(
            'flex min-h-12 items-center justify-between gap-3 rounded-xl border border-border bg-card px-3.5 text-left text-sm font-semibold text-ink-2 hover:bg-muted disabled:opacity-60',
            FOCUS,
          )}
        >
          <span data-testid="split-summary" className="min-w-0 truncate">
            {summary}
          </span>
          <ChevronRight size={16} aria-hidden="true" className="shrink-0 text-muted-foreground" />
        </button>
      </div>

      <Failure error={write.error} />
      <Button
        type="submit"
        className="h-12 rounded-xl text-sm font-semibold"
        disabled={!ready || write.isPending}
      >
        {write.isPending ? t('shared.saving') : t('shared.add.save')}
      </Button>
      {!ready && (
        <p className="-mt-2 text-center text-[13px] text-muted-foreground">
          {groupId === null
            ? t('shared.add.needsGroup')
            : total <= 0
              ? t('shared.add.needsAmount')
              : description.trim() === ''
                ? t('shared.add.needsDescription')
                : split.people.length === 0
                  ? t('shared.split.needsPeople')
                  : shortfallText(draftShortfall(split, total) ?? 0, shownCurrency)}
        </p>
      )}
    </form>
      {splitting && (
        <SplitSheet
          members={members.map((m) => ({ ...m, name: displayName(m.name, m.is_me) }))}
          total={total}
          currency={shownCurrency}
          payer={paidBy ?? me?.id ?? 0}
          draft={split}
          onClose={() => setSplitting(false)}
          onDone={(next) => {
            setDraft({ group: groupId, draft: next })
            setSplitting(false)
          }}
        />
      )}
    </>
  )
}
