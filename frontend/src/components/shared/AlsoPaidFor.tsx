import { useId } from 'react'
import { FIELD } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { CoverDraft } from '@/lib/coverDraft'
import { amountCents, convertCents, rateText, shortfallText } from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import type { Member } from '@/lib/sharedApi'
import { cn } from '@/lib/utils'
import { LIST_CARD } from './styles'

const LABEL = 'text-[13px] font-semibold text-ink-2'

interface AlsoPaidForProps {
  draft: CoverDraft
  payer: Member
  people: readonly Member[]
  currency: string
  legend: string
  hint: string
}

/** The checkboxes and amounts of "Also paid for…": the payer's own part first, then each person
 * checked; a part in the currency of someone's claims shows its conversion
 * ("RD$ 40,087.05 = US$ 629.31 · rate 63.70 of Feb"). The amounts must add up to the payment. */
export function AlsoPaidFor({ draft, payer, people, currency, legend, hint }: AlsoPaidForProps) {
  const ids = useId()
  const on = new Set(draft.covers)
  const proposal = draft.proposal
  const conversion = (member: Member) => {
    const part = proposal?.allocations.find((a) => a.contact_id === member.id)
    const cents = amountCents(draft.shares[member.id] ?? '', true)
    if (!proposal?.rate || !part?.equivalent || !cents) return null
    const converted = convertCents(cents, currency, part.equivalent.currency, proposal.rate)
    return t('shared.rate.conversion', {
      amount: formatMoney(cents, currency),
      converted: formatMoney(converted, part.equivalent.currency),
      rate: rateText(proposal.rate),
    })
  }
  const field = (member: Member) => (
    <input
      id={`${ids}-${member.id}`}
      aria-label={t('shared.pay.allocationOf', { name: member.name })}
      inputMode="decimal"
      value={draft.shares[member.id] ?? ''}
      placeholder="0"
      onChange={(event) => draft.type(member.id, event.target.value)}
      className={cn(FIELD, 'w-28 shrink-0 text-right tabular-nums')}
    />
  )
  const note = (member: Member) => {
    const text = conversion(member)
    return text ? (
      <span data-testid="allocation-conversion" className="text-[12px] text-muted-foreground">
        {text}
      </span>
    ) : null
  }
  return (
    <fieldset className="flex flex-col">
      <legend className={cn(LABEL, 'pb-1')}>{legend}</legend>
      <p className="pb-2 text-[13px] text-muted-foreground">{hint}</p>
      <ul className={LIST_CARD}>
        {draft.covers.length > 0 && (
          <li className="flex flex-col gap-0.5 px-3.5 py-1.5">
            <span className="flex min-h-11 items-center gap-3">
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{payer.name}</span>
              {field(payer)}
            </span>
            {note(payer)}
          </li>
        )}
        {people.map((member) => (
          <li key={member.id} className="flex flex-col gap-0.5 px-3.5 py-0.5">
            <span className="flex min-h-12 items-center gap-3">
              <label className="flex min-h-12 min-w-0 flex-1 cursor-pointer items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  aria-label={t('shared.pay.coversLabel', { name: member.name })}
                  checked={on.has(member.id)}
                  onChange={(event) => draft.toggle(member.id, event.target.checked)}
                  className="size-5 shrink-0 cursor-pointer accent-primary"
                />
                <span className="min-w-0 truncate font-medium">{member.name}</span>
              </label>
              {on.has(member.id) && field(member)}
            </span>
            {on.has(member.id) && note(member)}
          </li>
        ))}
      </ul>
      {draft.covers.length > 0 && (
        <p
          aria-live="polite"
          data-testid="allocation-shortfall"
          className={cn('min-h-5 pt-2 text-sm font-semibold', draft.missing === 0 ? 'text-down' : 'text-up')}
        >
          {draft.missing === null ? '' : shortfallText(draft.missing, currency)}
        </p>
      )}
    </fieldset>
  )
}
