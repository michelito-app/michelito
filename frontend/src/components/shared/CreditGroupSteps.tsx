// The list steps of "a new group from a credit": the expense it pays back (search, checkboxes,
// or one typed by hand) and the other credits of the same group.
import { Check, Plus } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { FIELD } from '@/components/transactions/linkParts'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { LinkedTx } from '@/lib/api'
import {
  type ChosenExpense,
  type CreditOption,
  type ExpenseOption,
  expenseCents,
  parseCents,
  personOf,
  searchExpenses,
} from '@/lib/creditGroup'
import type { ChosenPerson } from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'
import { Chip } from './parts'
import { LIST_CARD } from './styles'

const LABEL = 'text-[13px] font-semibold text-ink-2'
const CHECK_ROW = cn(
  // `relative`: the visually hidden input stays inside its row; otherwise it sits far down the
  // dialog and focusing it scrolls the whole dialog (seen on a wide screen).
  'relative flex min-h-14 w-full cursor-pointer items-center gap-3 px-3.5 py-2 text-left has-[:checked]:bg-secondary/60 hover:bg-muted/60',
  'has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/40 has-[:focus-visible]:ring-inset',
)

function CheckMark({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'flex size-6 shrink-0 items-center justify-center rounded-md border',
        on ? 'border-primary bg-primary text-primary-foreground' : 'border-[#D6D6D0] bg-card',
      )}
    >
      {on && <Check size={16} />}
    </span>
  )
}

function TxLine({ tx, badge }: { tx: LinkedTx; badge?: boolean }) {
  return (
    <>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-semibold">{tx.merchant}</span>
          {badge && (
            <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[12px] font-semibold text-secondary-foreground">
              {t('shared.credit.fits')}
            </span>
          )}
        </span>
        <span className="truncate text-[13px] text-muted-foreground">
          {shortDay(tx.day)}
          {tx.account_label ? ` · ${tx.account_label}` : ''}
        </span>
      </span>
      <span className="shrink-0 text-sm font-semibold tabular-nums">
        {formatMoney(Math.abs(tx.amount_cents), tx.currency)}
      </span>
    </>
  )
}

interface ExpenseStepProps {
  options: readonly ExpenseOption[]
  chosen: readonly ChosenExpense[]
  onChange: (chosen: ChosenExpense[]) => void
  creditDay: string
  currency: string
}

/** "Which expense is it paying back?": the plan's options (those that fit first), a search by
 * merchant or amount, and "Not in my bank" for one typed by hand. Several can be checked. */
export function ExpenseStep({ options, chosen, onChange, creditDay, currency }: ExpenseStepProps) {
  const ids = useId()
  const [query, setQuery] = useState('')
  const picked = new Set(chosen.map((c) => c.key))
  const found = searchExpenses(options, query)
  const hiddenPicked = options.filter((o) => picked.has(o.fingerprint) && !found.includes(o))
  const shown = [...hiddenPicked, ...found]
  const cash = chosen.filter((c) => c.kind === 'cash')
  const total = chosen.reduce((sum, c) => sum + expenseCents(c), 0)

  function toggle(tx: LinkedTx) {
    onChange(
      picked.has(tx.fingerprint)
        ? chosen.filter((c) => c.key !== tx.fingerprint)
        : [...chosen, { kind: 'tx', key: tx.fingerprint, tx }],
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t('shared.credit.expenseHint')}</p>
      <label htmlFor={`${ids}-q`} className="sr-only">
        {t('shared.credit.search')}
      </label>
      <input
        id={`${ids}-q`}
        type="search"
        value={query}
        maxLength={80}
        autoComplete="off"
        placeholder={t('shared.credit.search')}
        onChange={(event) => setQuery(event.target.value)}
        className={FIELD}
      />
      {chosen.length > 0 && (
        <p aria-live="polite" className="text-[13px] font-semibold text-primary">
          {t('shared.credit.chosenCount', {
            count: chosen.length,
            amount: formatMoney(total, chosen.length === 1 ? (chosen[0].kind === 'tx' ? chosen[0].tx.currency : chosen[0].currency) : currency),
          })}
        </p>
      )}
      <ul className={LIST_CARD} aria-label={t('shared.credit.expense')}>
        {cash.map((item) => (
          <li key={item.key}>
            <label className={CHECK_ROW}>
              <input
                type="checkbox"
                className="sr-only"
                checked
                onChange={() => onChange(chosen.filter((c) => c.key !== item.key))}
              />
              <CheckMark on />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-semibold">
                  {t('shared.credit.cashLabel', { description: item.description })}
                </span>
                <span className="text-[13px] text-muted-foreground">{shortDay(item.day)}</span>
              </span>
              <span className="shrink-0 text-sm font-semibold tabular-nums">
                {formatMoney(item.amount_cents, item.currency)}
              </span>
            </label>
          </li>
        ))}
        {shown.map((option) => (
          <li key={option.fingerprint}>
            <label className={CHECK_ROW}>
              <input
                type="checkbox"
                className="sr-only"
                checked={picked.has(option.fingerprint)}
                onChange={() => toggle(option)}
              />
              <CheckMark on={picked.has(option.fingerprint)} />
              <TxLine tx={option} badge={option.fits} />
            </label>
          </li>
        ))}
        {shown.length === 0 && cash.length === 0 && (
          <li className="px-3.5 py-3 text-sm text-muted-foreground">{t('shared.credit.noExpenses')}</li>
        )}
      </ul>
      <CashForm
        day={creditDay}
        currency={currency}
        onAdd={(item) => onChange([...chosen, item])}
      />
    </div>
  )
}

function CashForm({
  day,
  currency,
  onAdd,
}: {
  day: string
  currency: string
  onAdd: (item: ChosenExpense) => void
}) {
  const ids = useId()
  const [open, setOpen] = useState(false)
  const [description, setDescription] = useState('')
  const [amount, setAmount] = useState('')
  const [when, setWhen] = useState(day)
  const [bad, setBad] = useState(false)

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          'inline-flex min-h-11 items-center gap-2 self-start rounded-xl px-2 text-sm font-semibold text-primary hover:bg-muted',
          FOCUS,
        )}
      >
        <Plus size={16} aria-hidden="true" />
        {t('shared.credit.cash')}
      </button>
    )
  }

  function add() {
    const cents = parseCents(amount)
    const text = description.trim()
    if (cents === null || !text || !when) {
      setBad(true)
      return
    }
    onAdd({ kind: 'cash', key: `cash-${Date.now()}`, description: text, amount_cents: cents, currency, day: when })
    setDescription('')
    setAmount('')
    setBad(false)
    setOpen(false)
  }

  return (
    <fieldset className="flex flex-col gap-2 rounded-2xl border border-border p-3">
      <legend className={cn(LABEL, 'px-1')}>{t('shared.credit.cash')}</legend>
      <p className="text-[13px] text-muted-foreground">{t('shared.credit.cashHint')}</p>
      <label htmlFor={`${ids}-d`} className={LABEL}>
        {t('shared.credit.cashDescription')}
      </label>
      <input
        id={`${ids}-d`}
        value={description}
        maxLength={120}
        onChange={(event) => setDescription(event.target.value)}
        className={FIELD}
      />
      <div className="grid grid-cols-2 gap-2">
        <label className={cn(LABEL, 'flex flex-col gap-1.5')}>
          {t('shared.credit.cashAmount')}
          <input
            inputMode="decimal"
            value={amount}
            maxLength={16}
            onChange={(event) => setAmount(event.target.value)}
            className={FIELD}
          />
        </label>
        <label className={cn(LABEL, 'flex flex-col gap-1.5')}>
          {t('shared.credit.cashDay')}
          <input
            type="date"
            value={when}
            max={day}
            onChange={(event) => setWhen(event.target.value)}
            className={FIELD}
          />
        </label>
      </div>
      {bad && (
        <p role="alert" className="text-[13px] text-up-ink">
          {t('shared.credit.cashBad')}
        </p>
      )}
      <Button type="button" variant="outline" className="h-11 rounded-xl text-sm font-semibold" onClick={add}>
        {t('shared.credit.cashAdd')}
      </Button>
    </fieldset>
  )
}

interface OthersStepProps {
  options: readonly CreditOption[]
  payer: ChosenPerson
  /** Checked credits and who sent them (null: the main payer, whoever it is by then). */
  chosen: ReadonlyMap<string, ChosenPerson | null>
  onChange: (chosen: Map<string, ChosenPerson | null>) => void
}

/** "Anything else of this group?": other credits near this one; none is preselected. A checked
 * one asks who sent it (the guessed person or the main payer). */
export function OthersStep({ options, payer, chosen, onChange }: OthersStepProps) {
  if (options.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('shared.credit.noOthers')}</p>
  }

  function toggle(option: CreditOption) {
    const next = new Map(chosen)
    if (next.has(option.tx.fingerprint)) next.delete(option.tx.fingerprint)
    else next.set(option.tx.fingerprint, personOf(option.person))
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted-foreground">{t('shared.credit.othersHint')}</p>
      <ul className={LIST_CARD} aria-label={t('shared.credit.others')}>
        {options.map((option) => {
          const checked = chosen.has(option.tx.fingerprint)
          const who = checked ? (chosen.get(option.tx.fingerprint) ?? payer) : undefined
          const guessed = personOf(option.person)
          const people = guessed && guessed.key !== payer.key ? [payer, guessed] : [payer]
          return (
            <li key={option.tx.fingerprint}>
              <label className={CHECK_ROW}>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={who !== undefined}
                  onChange={() => toggle(option)}
                />
                <CheckMark on={who !== undefined} />
                <TxLine tx={option.tx} />
              </label>
              {who && people.length > 1 && (
                <fieldset className="flex flex-col gap-2 px-3.5 pb-3">
                  <legend className={cn(LABEL, 'pb-2')}>{t('shared.credit.fromWho')}</legend>
                  <div className="flex flex-wrap gap-2">
                    {people.map((person) => (
                      <Chip
                        key={person.key}
                        on={person.key === who.key}
                        onClick={() =>
                          onChange(
                            new Map(chosen).set(option.tx.fingerprint, person.key === payer.key ? null : person),
                          )
                        }
                      >
                        {person.label}
                      </Chip>
                    ))}
                  </div>
                </fieldset>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
