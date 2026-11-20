import { useId, useState } from 'react'
import { FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  displayName,
  draftShortfall,
  draftValid,
  equalShares,
  shortfallText,
  type SplitDraft,
} from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import type { Member } from '@/lib/sharedApi'
import { cn } from '@/lib/utils'

export type SplitMember = Pick<Member, 'id' | 'name' | 'is_me'>

interface SplitSheetProps {
  members: readonly SplitMember[]
  total: number
  currency: string
  payer: number
  draft: SplitDraft
  onDone: (draft: SplitDraft) => void
  onClose: () => void
}

/** The split: checkable people and "Exact amounts", with the live "RD$ 200 missing"; "Done" is
 * disabled until it adds up. */
export function SplitSheet({ members, total, currency, payer, draft, onDone, onClose }: SplitSheetProps) {
  const ids = useId()
  const [current, setCurrent] = useState<SplitDraft>(draft)
  const chosen = new Set(current.people)
  const missing = draftShortfall(current, total)
  const valid = draftValid(current, total)
  const preview = new Map(
    equalShares(total, current.people, payer).map((share) => [share.contact_id, share.cents]),
  )

  function toggle(id: number) {
    const people = chosen.has(id)
      ? current.people.filter((p) => p !== id)
      : members.map((m) => m.id).filter((m) => m === id || chosen.has(m))
    setCurrent({ ...current, people })
  }

  return (
    <BottomSheet title={t('shared.split.title')} onClose={onClose}>
      <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm font-semibold">
        <input
          type="checkbox"
          checked={current.mode === 'exact'}
          onChange={(event) =>
            setCurrent({ ...current, mode: event.target.checked ? 'exact' : 'equal' })
          }
          className="size-5 shrink-0 cursor-pointer accent-primary"
        />
        {t('shared.split.exact')}
      </label>
      <fieldset className="flex flex-col">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">{t('shared.split.people')}</legend>
        <ul className="flex flex-col overflow-hidden rounded-xl border border-border">
          {members.map((member) => {
            const name = displayName(member.name, member.is_me)
            const on = chosen.has(member.id)
            return (
              <li
                key={member.id}
                className="flex min-h-12 items-center gap-3 border-b border-border px-3 last:border-b-0"
              >
                <label className="flex min-h-12 min-w-0 flex-1 cursor-pointer items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggle(member.id)}
                    className="size-5 shrink-0 cursor-pointer accent-primary"
                  />
                  <span className="min-w-0 truncate font-medium">{name}</span>
                </label>
                {on && current.mode === 'exact' ? (
                  <input
                    id={`${ids}-${member.id}`}
                    aria-label={t('shared.split.amountOf', { name })}
                    inputMode="decimal"
                    value={current.shares[member.id] ?? ''}
                    placeholder="0"
                    onChange={(event) =>
                      setCurrent({
                        ...current,
                        shares: { ...current.shares, [member.id]: event.target.value },
                      })
                    }
                    className={cn(FIELD, 'w-28 shrink-0 text-right tabular-nums')}
                  />
                ) : (
                  on && (
                    <span className="shrink-0 text-sm text-muted-foreground tabular-nums">
                      {formatMoney(preview.get(member.id) ?? 0, currency)}
                    </span>
                  )
                )}
              </li>
            )
          })}
        </ul>
      </fieldset>
      <p
        aria-live="polite"
        data-testid="split-shortfall"
        className={cn(
          'min-h-5 text-sm font-semibold',
          current.people.length === 0 || (missing !== null && missing !== 0) ? 'text-up' : 'text-down',
        )}
      >
        {current.people.length === 0
          ? t('shared.split.needsPeople')
          : current.mode === 'exact' && missing !== null
            ? shortfallText(missing, currency)
            : ''}
      </p>
      <Button
        className="h-11 rounded-xl text-sm font-semibold"
        disabled={!valid}
        onClick={() => onDone(current)}
      >
        {t('shared.done')}
      </Button>
    </BottomSheet>
  )
}
