import { Minus, Plus } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { FIELD } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import {
  displayName,
  draftAmounts,
  draftShortfall,
  draftValid,
  setParts,
  shortfallText,
  switchMode,
  togglePerson,
  type SplitDraft,
} from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import type { Member, SplitMode } from '@/lib/sharedApi'
import { cn } from '@/lib/utils'
import { CHIP, CHIP_OFF, CHIP_ON } from './styles'

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

const MODES: readonly { mode: SplitMode; label: () => string }[] = [
  { mode: 'equal', label: () => t('shared.split.equal') },
  { mode: 'exact', label: () => t('shared.split.exact') },
  { mode: 'parts', label: () => t('shared.split.parts') },
]

/** The split: equal, exact amounts or by parts, with checkable people. Switching to exact
 * amounts starts from the current split (only the different one needs editing) and shows the
 * live "RD$ 200 missing"; by parts, each person has − / + steppers. "Done" is disabled until it
 * adds up. */
export function SplitSheet({ members, total, currency, payer, draft, onDone, onClose }: SplitSheetProps) {
  const ids = useId()
  const [current, setCurrent] = useState<SplitDraft>(draft)
  const chosen = new Set(current.people)
  const missing = draftShortfall(current, total)
  const valid = draftValid(current, total)
  const preview = draftAmounts(current, total, payer)
  const order = members.map((m) => m.id)

  return (
    <BottomSheet title={t('shared.split.title')} onClose={onClose}>
      <fieldset className="flex flex-col">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">{t('shared.split.mode')}</legend>
        <div className="flex flex-wrap gap-2">
          {MODES.map(({ mode, label }) => (
            <label
              key={mode}
              className={cn(
                CHIP,
                current.mode === mode ? CHIP_ON : CHIP_OFF,
                'cursor-pointer',
              )}
            >
              <input
                type="radio"
                name={`${ids}-mode`}
                value={mode}
                checked={current.mode === mode}
                onChange={() => setCurrent(switchMode(current, mode, total, payer))}
                className="size-4 shrink-0 cursor-pointer accent-primary"
              />
              {label()}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="flex flex-col">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">{t('shared.split.people')}</legend>
        <ul className="flex flex-col overflow-hidden rounded-xl border border-border">
          {members.map((member) => {
            const name = displayName(member.name, member.is_me)
            const on = chosen.has(member.id)
            return (
              <li
                key={member.id}
                className="flex min-h-12 flex-wrap items-center gap-x-3 border-b border-border px-3 last:border-b-0"
              >
                <label className="flex min-h-12 min-w-0 flex-1 cursor-pointer items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => setCurrent(togglePerson(current, member.id, order))}
                    className="size-5 shrink-0 cursor-pointer accent-primary"
                  />
                  <span className="min-w-0 truncate font-medium">{name}</span>
                </label>
                {on && current.mode === 'exact' && (
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
                )}
                {on && current.mode === 'parts' && (
                  <Stepper
                    name={name}
                    parts={current.parts?.[member.id] ?? 1}
                    onChange={(parts) => setCurrent(setParts(current, member.id, parts))}
                  />
                )}
                {on && current.mode !== 'exact' && (
                  <span
                    data-testid="split-amount"
                    className="shrink-0 text-sm text-muted-foreground tabular-nums"
                  >
                    {formatMoney(preview[member.id] ?? 0, currency)}
                  </span>
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

const STEP = cn(
  'flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-ink-2 hover:bg-muted disabled:opacity-40',
  FOCUS,
)

/** − parts + (44 px each), at least 1. */
function Stepper({ name, parts, onChange }: { name: string; parts: number; onChange: (parts: number) => void }) {
  return (
    <div role="group" aria-label={t('shared.split.partsOf', { name })} className="flex shrink-0 items-center gap-1">
      <button
        type="button"
        aria-label={t('shared.split.lessPart', { name })}
        disabled={parts <= 1}
        onClick={() => onChange(parts - 1)}
        className={STEP}
      >
        <Minus size={16} aria-hidden="true" />
      </button>
      <span data-testid="split-parts" className="w-7 text-center text-sm font-semibold tabular-nums">
        {parts}
      </span>
      <button
        type="button"
        aria-label={t('shared.split.morePart', { name })}
        onClick={() => onChange(parts + 1)}
        className={STEP}
      >
        <Plus size={16} aria-hidden="true" />
      </button>
    </div>
  )
}
