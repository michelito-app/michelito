// "+ New group" from a credit: who paid → the expense it pays back → other credits of the same
// group → name and split. One request creates all of it (one change in the log, one undo).
import { ArrowLeft } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Failure, FIELD, LoadFailure } from '@/components/transactions/linkParts'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
import type { LinkedTx, Tx } from '@/lib/api'
import {
  type ChosenCredit,
  type ChosenExpense,
  type CreditSplit,
  creditGroupBody,
  defaultName,
  personOf,
  type SplitPreview,
  splitPreview,
} from '@/lib/creditGroup'
import type { ChosenPerson } from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import { ledger, useCreditPlan, useLedgerWrite } from '@/lib/sharedQueries'
import { cn } from '@/lib/utils'
import { ExpenseStep, OthersStep } from './CreditGroupSteps'
import { PeoplePicker } from './PeoplePicker'

const STEPS = ['who', 'expense', 'others', 'confirm'] as const
type Step = (typeof STEPS)[number]
const LABEL = 'text-[13px] font-semibold text-ink-2'
const TITLES: Record<Step, Parameters<typeof t>[0]> = {
  who: 'shared.credit.who',
  expense: 'shared.credit.expense',
  others: 'shared.credit.others',
  confirm: 'shared.credit.confirm',
}

interface CreditGroupFlowProps {
  tx: Tx
  /** Back to picking an existing group. */
  onBack: (() => void) | null
  onDone: () => void
}

export function CreditGroupFlow({ tx, onBack, onDone }: CreditGroupFlowProps) {
  const plan = useCreditPlan(tx.fingerprint, true)
  const write = useLedgerWrite()
  const [step, setStep] = useState<Step>('who')
  const [payerChoice, setPayer] = useState<ChosenPerson | null | undefined>(undefined)
  const [expenses, setExpenses] = useState<ChosenExpense[]>([])
  const [others, setOthers] = useState<Map<string, ChosenPerson | null>>(new Map())
  const [nameChoice, setName] = useState<string | null>(null)
  const [splitChoice, setSplit] = useState<CreditSplit | null>(null)

  if (plan.isError) return <LoadFailure what={t('shared.load')} error={plan.error} />
  if (plan.isPending) return <p className="text-[13px] text-muted-foreground">{t('shared.loading')}</p>

  const payer = payerChoice === undefined ? personOf(plan.data.person) : payerChoice
  const credit: LinkedTx = { ...tx, description: tx.description }
  const credits: ChosenCredit[] = payer
    ? [
        { tx: credit, payer },
        ...plan.data.credits
          .filter((o) => others.has(o.tx.fingerprint))
          .map((o) => ({ tx: o.tx, payer: others.get(o.tx.fingerprint) ?? payer })),
      ]
    : []
  const preview = splitPreview(expenses, credits)
  const split = preview.paidAllowed ? (splitChoice ?? preview.defaultSplit) : 'equal'
  const name = nameChoice ?? defaultName(expenses)
  const index = STEPS.indexOf(step)
  const canNext =
    (step === 'who' && payer !== null) ||
    (step === 'expense' && expenses.length > 0) ||
    step === 'others' ||
    (step === 'confirm' && name.trim() !== '' && !write.isPending)

  function next() {
    if (step !== 'confirm') {
      setStep(STEPS[index + 1])
      return
    }
    write.mutate(() => ledger.groupFromCredit(creditGroupBody(name, split, expenses, credits)), {
      onSuccess: onDone,
    })
  }

  const back = index > 0 ? () => setStep(STEPS[index - 1]) : onBack

  return (
    <div className="flex flex-1 flex-col gap-4" data-testid="credit-group-flow">
      <div className="-mt-2 flex items-center justify-between gap-2">
        {back ? (
          <button
            type="button"
            onClick={back}
            className={cn(
              '-ml-2 inline-flex min-h-11 items-center gap-1.5 rounded-xl px-2 text-sm font-semibold text-primary hover:bg-muted',
              FOCUS,
            )}
          >
            <ArrowLeft size={16} aria-hidden="true" />
            {t('shared.back')}
          </button>
        ) : (
          <span />
        )}
        <span className="text-[13px] text-muted-foreground">
          {t('shared.credit.step', { n: index + 1, total: STEPS.length })}
        </span>
      </div>
      <h3 className="text-[17px] font-[650] tracking-tight">{t(TITLES[step])}</h3>
      <p className="-mt-2 text-sm font-semibold">
        {tx.merchant} · {formatMoney(Math.abs(tx.amount_cents), tx.currency)}
      </p>
      {step === 'who' && (
        <div className="flex flex-col gap-2">
          <p className="text-[13px] text-muted-foreground">{t('shared.credit.whoHint')}</p>
          <PeoplePicker
            chosen={payer ? [payer] : []}
            withMe={false}
            onChange={(list) => setPayer(list.at(-1) ?? null)}
          />
        </div>
      )}
      {step === 'expense' && (
        <ExpenseStep
          options={plan.data.expenses}
          chosen={expenses}
          onChange={setExpenses}
          creditDay={tx.day}
          currency={tx.currency}
        />
      )}
      {step === 'others' && payer && (
        <OthersStep options={plan.data.credits} payer={payer} chosen={others} onChange={setOthers} />
      )}
      {step === 'confirm' && (
        <Confirm
          name={name}
          onName={setName}
          credits={credits}
          preview={preview}
          split={split}
          onSplit={setSplit}
        />
      )}
      <Failure error={write.error} />
      {/* Pinned to the bottom; the sheet drops its own bottom padding for it (WebKit sticks above
          that padding and the list would show under the button). */}
      <div className="sticky bottom-0 -mx-4 mt-auto border-t border-border bg-card px-4 pt-3 pb-[max(16px,env(safe-area-inset-bottom))]">
        <Button className="h-12 w-full rounded-xl text-[15px] font-semibold" disabled={!canNext} onClick={next}>
          {step === 'confirm'
            ? write.isPending
              ? t('shared.saving')
              : t('shared.credit.create')
            : step === 'others' && others.size === 0
              ? t('shared.credit.skip')
              : t('shared.credit.next')}
        </Button>
      </div>
    </div>
  )
}

interface ConfirmProps {
  name: string
  onName: (name: string) => void
  credits: readonly ChosenCredit[]
  preview: SplitPreview
  split: CreditSplit
  onSplit: (split: CreditSplit) => void
}

function Confirm({ name, onName, credits, preview, split, onSplit }: ConfirmProps) {
  const ids = useId()
  const currency = preview.currency ?? credits[0]?.tx.currency ?? 'DOP'
  const money = (cents: number) => formatMoney(cents, currency)
  const equalHint = preview.equalSettles ? 'shared.credit.splitEqualSettles' : 'shared.credit.splitEqualHint'
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${ids}-name`} className={LABEL}>
          {t('shared.credit.name')}
        </label>
        <input
          id={`${ids}-name`}
          value={name}
          maxLength={80}
          required
          placeholder={t('shared.newGroup.namePlaceholder')}
          onChange={(event) => onName(event.target.value)}
          className={FIELD}
        />
      </div>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 rounded-2xl border border-border p-3.5 text-sm">
        <dt className="text-muted-foreground">{t('shared.credit.totalExpenses')}</dt>
        <dd className="text-right font-semibold tabular-nums">{money(preview.totalCents)}</dd>
        <dt className="text-muted-foreground">{t('shared.credit.totalPaid')}</dt>
        <dd className="text-right font-semibold tabular-nums">{money(preview.paidCents)}</dd>
      </dl>
      <ul className="flex flex-col gap-1 text-[13px] text-ink-2">
        {credits.map((c) => (
          <li key={c.tx.fingerprint}>
            {t('shared.credit.paidBy', {
              name: c.payer.label,
              amount: formatMoney(Math.abs(c.tx.amount_cents), c.tx.currency),
            })}
          </li>
        ))}
      </ul>
      <fieldset className="flex flex-col gap-2">
        <legend className={cn(LABEL, 'pb-2')}>{t('shared.credit.split')}</legend>
        {!preview.paidAllowed && (
          <p className="text-[13px] text-muted-foreground">{t('shared.credit.paidNotAllowed')}</p>
        )}
        {preview.paidAllowed && (
          <SplitOption
            name={`${ids}-split`}
            checked={split === 'paid'}
            onCheck={() => onSplit('paid')}
            title={t('shared.credit.splitPaid')}
            hint={t('shared.credit.splitPaidHint', { mine: money(preview.mineCents) })}
          />
        )}
        <SplitOption
          name={`${ids}-split`}
          checked={split === 'equal'}
          onCheck={() => onSplit('equal')}
          title={t('shared.credit.splitEqual')}
          hint={t(equalHint, { share: money(preview.equalCents), people: preview.people })}
        />
      </fieldset>
    </div>
  )
}

function SplitOption(props: {
  name: string
  checked: boolean
  onCheck: () => void
  title: string
  hint: string
}) {
  return (
    <label
      className={cn(
        'flex min-h-14 cursor-pointer items-start gap-3 rounded-2xl border px-3.5 py-3',
        'has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/40',
        props.checked ? 'border-primary bg-secondary/60' : 'border-border hover:bg-muted/60',
      )}
    >
      <input
        type="radio"
        name={props.name}
        checked={props.checked}
        onChange={props.onCheck}
        className="mt-1 size-4 accent-[var(--primary)]"
      />
      <span className="flex flex-col">
        <span className="text-sm font-semibold">{props.title}</span>
        <span className="text-[13px] text-muted-foreground">{props.hint}</span>
      </span>
    </label>
  )
}
