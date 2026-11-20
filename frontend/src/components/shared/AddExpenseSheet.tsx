import { ArrowLeft, ChevronRight, Landmark, UsersRound } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import type { Candidate, LinkedTx } from '@/lib/api'
import { formatMoney } from '@/lib/links'
import { shortDay } from '@/lib/months'
import type { Group } from '@/lib/sharedApi'
import { useExpenseCandidates, useSharedHome } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { ExpenseForm } from './ExpenseForm'
import { NewGroupSheet } from './NewGroupSheet'
import { LIST_CARD, ROW_BUTTON } from './styles'

type Step = 'paths' | 'pick' | 'mine' | 'other'

interface AddExpenseSheetProps {
  /** Entering from inside a group preselects it. */
  groupId?: number | null
  /** Entering from a transaction's "Share": straight to "I paid it" with it. */
  tx?: LinkedTx | null
  onClose: () => void
  onSaved: (group: Group) => void
}

/** "Add expense": two paths. "I paid it" picks a recent bank expense (likely ones first);
 * "Someone else paid it" is a full-screen form. Then the group (or "+ New group" without losing
 * the draft) and the split. */
export function AddExpenseSheet({ groupId = null, tx = null, onClose, onSaved }: AddExpenseSheetProps) {
  const [step, setStep] = useState<Step>(tx ? 'mine' : 'paths')
  const [chosen, setChosen] = useState<LinkedTx | null>(tx)
  const [creating, setCreating] = useState(false)
  const home = useSharedHome()
  const groups = (home.data?.groups ?? []).filter((g) => !g.archived)
  const [picked, setPicked] = useState<number | null>(groupId)
  const group = picked ?? groups[0]?.id ?? null

  const title =
    step === 'pick'
      ? t('shared.add.pickTitle')
      : step === 'mine'
        ? t('shared.add.mine')
        : step === 'other'
          ? t('shared.add.other')
          : t('shared.add.title')
  const back: Step | null = step === 'pick' || step === 'other' ? 'paths' : step === 'mine' && !tx ? 'pick' : null

  return (
    <BottomSheet title={title} onClose={onClose} full={step === 'other'}>
      {back && (
        <button
          type="button"
          onClick={() => setStep(back)}
          className={cn(
            '-mt-2 -ml-2 inline-flex min-h-11 items-center gap-1.5 self-start rounded-xl px-2 text-sm font-semibold text-primary hover:bg-muted',
            FOCUS,
          )}
        >
          <ArrowLeft size={16} aria-hidden="true" />
          {t('shared.back')}
        </button>
      )}
      {step === 'paths' && (
        <ul className={LIST_CARD} aria-label={t('shared.add.how')}>
          <PathRow
            icon={<Landmark size={20} aria-hidden="true" />}
            title={t('shared.add.mine')}
            hint={t('shared.add.mineHint')}
            onClick={() => setStep('pick')}
          />
          <PathRow
            icon={<UsersRound size={20} aria-hidden="true" />}
            title={t('shared.add.other')}
            hint={t('shared.add.otherHint')}
            onClick={() => setStep('other')}
          />
        </ul>
      )}
      {step === 'pick' && (
        <CandidateList
          onPick={(candidate) => {
            setChosen(candidate)
            setStep('mine')
          }}
        />
      )}
      {(step === 'mine' || step === 'other') && (
        <ExpenseForm
          key={step === 'mine' ? (chosen?.fingerprint ?? 'mine') : 'other'}
          tx={step === 'mine' ? chosen : null}
          groups={groups}
          groupId={group}
          onGroup={setPicked}
          onNewGroup={() => setCreating(true)}
          onSaved={onSaved}
        />
      )}
      {creating && (
        <NewGroupSheet
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setPicked(created.id)
            setCreating(false)
          }}
        />
      )}
    </BottomSheet>
  )
}

function PathRow({
  icon,
  title,
  hint,
  onClick,
}: {
  icon: ReactNode
  title: string
  hint: string
  onClick: () => void
}) {
  return (
    <li>
      <button type="button" onClick={onClick} className={ROW_BUTTON}>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
          {icon}
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-[15px] font-semibold">{title}</span>
          <span className="text-[13px] text-muted-foreground">{hint}</span>
        </span>
        <ChevronRight size={18} aria-hidden="true" className="shrink-0 text-muted-foreground" />
      </button>
    </li>
  )
}

/** "I paid it": recent expenses not in a group; the likely ones (restaurants, groceries,
 * round amounts) first. */
function CandidateList({ onPick }: { onPick: (candidate: Candidate) => void }) {
  const candidates = useExpenseCandidates(true)
  if (candidates.isError) return <LoadFailure what={t('shared.load')} error={candidates.error} />
  if (candidates.isPending) {
    return <p className="text-[13px] text-muted-foreground">{t('shared.loading')}</p>
  }
  const items = candidates.data
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('shared.add.noCandidates')}</p>
  }
  const likely = items.filter((c) => c.primary)
  const rest = items.filter((c) => !c.primary)
  return (
    <section aria-label={t('shared.add.candidates')} className="flex flex-col gap-3">
      {[
        { label: t('shared.add.likely'), list: likely },
        { label: t('shared.add.more'), list: rest },
      ]
        .filter((block) => block.list.length > 0)
        .map((block) => (
          <div key={block.label} className="flex flex-col gap-1.5">
            <h3 className="text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase">
              {block.label}
            </h3>
            <ul className={LIST_CARD}>
              {block.list.map((candidate) => (
                <CandidateRow key={candidate.fingerprint} candidate={candidate} onPick={onPick} />
              ))}
            </ul>
          </div>
        ))}
    </section>
  )
}

function CandidateRow({ candidate, onPick }: { candidate: Candidate; onPick: (c: Candidate) => void }) {
  const amount = formatMoney(Math.abs(candidate.amount_cents), candidate.currency)
  return (
    <li>
      <button
        type="button"
        aria-label={t('shared.add.pickLabel', { merchant: candidate.merchant, amount })}
        onClick={() => onPick(candidate)}
        className={ROW_BUTTON}
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-semibold">{candidate.merchant}</span>
          <span className="truncate text-[13px] text-muted-foreground">
            {shortDay(candidate.day)} · {candidate.account_label}
          </span>
        </span>
        <span className="shrink-0 text-sm font-semibold tabular-nums">{amount}</span>
      </button>
    </li>
  )
}
