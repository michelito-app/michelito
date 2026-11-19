import { useId, useState } from 'react'
import { t } from '@/i18n'
import type { SharedInfo } from '@/lib/api'
import { formatMoney, parseCents, shortDay, toggled } from '@/lib/links'
import { useChangeGroup, useGroupCreditCandidates } from '@/lib/queries'
import { CandidatePicker } from './CandidatePicker'
import { Action, Failure, FIELD, LinkedRow, LoadFailure } from './linkParts'

interface GroupRefundsProps {
  group: SharedInfo
  /** The open transaction: highlighted when it is one of the reimbursements. */
  current: string
}

/** The group's reimbursements (credits and manual ones), each with a remove button. */
export function GroupRefundList({ group, current }: GroupRefundsProps) {
  const change = useChangeGroup()
  if (group.reimbursements.length === 0 && group.manual.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{t('links.refund.none')}</p>
  }
  return (
    <>
      <ul aria-label={t('links.group.refunds')} className="flex flex-col gap-2">
        {group.reimbursements.map((item) => (
          <LinkedRow
            key={item.fingerprint}
            item={item}
            current={item.fingerprint === current}
            action={
              <Action
                label={t('links.refund.removeOf', { merchant: item.merchant })}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({ action: 'remove-credit', id: group.id, credit: item.fingerprint })
                }
              >
                {t('links.remove')}
              </Action>
            }
          />
        ))}
        {group.manual.map((entry) => (
          <li
            key={entry.id}
            className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[13px]"
          >
            <span className="flex min-w-0 flex-col">
              <span className="font-semibold break-words">
                {entry.place || t('links.refund.cash')}
                {entry.person && ` · ${entry.person}`} ({shortDay(entry.day)})
              </span>
              <span className="text-muted-foreground tabular-nums">
                {t('links.refund.manualAmount', {
                  amount: formatMoney(entry.amount_cents, entry.currency),
                })}
              </span>
            </span>
            <Action
              label={t('links.refund.removeManual', {
                amount: formatMoney(entry.amount_cents, entry.currency),
              })}
              disabled={change.isPending}
              onClick={() =>
                change.mutate({ action: 'remove-manual', id: group.id, manualId: entry.id })
              }
            >
              {t('links.remove')}
            </Action>
          </li>
        ))}
      </ul>
      <Failure error={change.error} />
    </>
  )
}

/** Add a reimbursement: an imported credit (picker) or one in cash or another account. */
export function AddRefund({ group }: { group: SharedInfo }) {
  const [manual, setManual] = useState(false)
  return (
    <div className="flex flex-col gap-2.5">
      <CreditPicker group={group} />
      <Action wide onClick={() => setManual((v) => !v)}>
        {t('links.refund.paidElsewhere')}
      </Action>
      {manual && <ManualForm group={group} onDone={() => setManual(false)} />}
    </div>
  )
}

/** Credits from any account, from the oldest expense to 4 months after the newest: first the
 * ones that fit what is pending, the rest behind "see more". */
function CreditPicker({ group }: { group: SharedInfo }) {
  const candidates = useGroupCreditCandidates(group.id, true)
  const change = useChangeGroup()
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set())

  /** One after another: if one fails it stops there, the error stays visible (`change.error`)
   * and the remaining ones stay selected. */
  async function link() {
    for (const credit of chosen) {
      try {
        await change.mutateAsync({ action: 'add-credit', id: group.id, credit })
      } catch {
        return
      }
      setChosen((current) => toggled(current, credit))
    }
  }

  if (candidates.isError) {
    return <LoadFailure what={t('links.what.credits')} error={candidates.error} />
  }
  if (candidates.isPending) {
    return <p className="text-[13px] text-muted-foreground">{t('links.searching')}</p>
  }
  const credits = candidates.data?.credits ?? []
  if (credits.length === 0) {
    return (
      <p className="text-[13px] text-muted-foreground">
        {t('links.refund.noCredits')}
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <CandidatePicker
        items={credits}
        chosen={chosen}
        onToggle={(fp) => setChosen((current) => toggled(current, fp))}
        label={t('links.refund.candidates')}
      />
      <div>
        <Action
          primary
          disabled={chosen.size === 0 || change.isPending}
          onClick={() => void link()}
        >
          {t('links.refund.linkCredits', { count: chosen.size })}
        </Action>
      </div>
      <Failure error={change.error} />
    </div>
  )
}

/** A reimbursement in cash or in an account that is not imported: amount (and currency when
 * the group has both), date, from whom and where. */
function ManualForm({ group, onDone }: { group: SharedInfo; onDone: () => void }) {
  const ids = useId()
  const candidates = useGroupCreditCandidates(group.id, true)
  const change = useChangeGroup()
  const currencies = [...new Set(group.expenses.map((e) => e.currency))]
  const [currency, setCurrency] = useState(group.expenses[0]?.currency ?? 'DOP')
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState(group.expenses.at(-1)?.day ?? '')
  const [person, setPerson] = useState(group.with_whom)
  const [place, setPlace] = useState(t('links.refund.cash'))
  const [error, setError] = useState<string | null>(null)

  function save() {
    const cents = parseCents(amount)
    if (cents === null) {
      setError(t('links.refund.amountError'))
      return
    }
    change.mutate(
      {
        action: 'add-manual',
        id: group.id,
        manual: {
          amount_cents: cents,
          day,
          person: person.trim() || null,
          place: place.trim() || null,
          currency: currency === 'USD' ? 'USD' : 'DOP',
        },
      },
      { onSuccess: onDone },
    )
  }

  const label = 'flex flex-col gap-1 text-[13px] font-semibold text-ink-2'
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
        <label className={label}>
          {t('links.refund.amount', { currency: currency === 'USD' ? 'US$' : 'RD$' })}
          <input
            inputMode="decimal"
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value)
              setError(null)
            }}
            className={FIELD}
          />
        </label>
        {currencies.length > 1 && (
          <label className={label}>
            {t('links.refund.currency')}
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className={FIELD}
            >
              <option value="DOP">RD$</option>
              <option value="USD">US$</option>
            </select>
          </label>
        )}
        <label className={label}>
          {t('links.refund.date')}
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={label}>
          {t('links.refund.person')}
          <input
            maxLength={80}
            value={person}
            onChange={(e) => setPerson(e.target.value)}
            className={FIELD}
          />
        </label>
        <label className={label}>
          {t('links.refund.place')}
          <input
            list={`${ids}-places`}
            maxLength={80}
            value={place}
            onChange={(e) => setPlace(e.target.value)}
            className={FIELD}
          />
          <datalist id={`${ids}-places`}>
            <option value={t('links.refund.cash')} />
            {(candidates.data?.places ?? []).map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
        </label>
      </div>
      <p className="text-[13px] text-muted-foreground">
        {t('links.refund.manualHint')}
      </p>
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
          {error}
        </p>
      )}
      <div>
        <Action primary disabled={change.isPending} onClick={save}>
          {t('links.refund.save')}
        </Action>
      </div>
      <Failure error={change.error} />
    </div>
  )
}
