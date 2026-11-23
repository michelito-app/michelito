import { Check, Clock, TriangleAlert, UsersRound } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { Action, ConfirmBox, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { InstallmentPlan, InstallmentState } from '@/lib/api'
import { useDeleteInstallment } from '@/lib/installmentQueries'
import {
  eachLine,
  installmentLabel,
  ownerLine,
  planSummary,
  progress,
} from '@/lib/installments'
import { groupPath } from '@/lib/links'
import { monthName } from '@/lib/months'
import { cn } from '@/lib/utils'

const STATE_CLASS: Record<InstallmentState, string> = {
  paid: 'border-primary/30 bg-[#F6FAF8] text-primary',
  pending: 'border-border bg-card text-muted-foreground',
  missing: 'border-up/40 bg-up-soft text-up-ink',
}

const STATE_ICON: Record<InstallmentState, ReactNode> = {
  paid: <Check size={12} aria-hidden="true" />,
  pending: <Clock size={12} aria-hidden="true" />,
  missing: <TriangleAlert size={12} aria-hidden="true" />,
}

/** A plan's card: how many are paid and what is left, each installment's state, whose it is (a
 * member's links to the group) and "Delete plan" with a confirmation. */
export function PlanCard({ plan }: { plan: InstallmentPlan }) {
  const titleId = useId()
  const owner = ownerLine(plan)
  const share = progress(plan)
  return (
    <article
      data-testid="installment-plan"
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded-xl border border-border bg-card px-4 py-3.5"
    >
      <header className="flex flex-col gap-0.5">
        <h3 id={titleId} className="text-[15px] font-bold break-words">
          {plan.name}
        </h3>
        <span className="text-[13px] text-muted-foreground tabular-nums">{eachLine(plan)}</span>
      </header>
      <div className="flex flex-col gap-1.5">
        <p data-testid="installment-summary" className="text-sm font-semibold tabular-nums">
          {planSummary(plan)}
        </p>
        <div
          aria-hidden="true"
          className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        >
          <div
            className="h-full origin-left rounded-full bg-primary transition-transform duration-300"
            style={{ transform: `scaleX(${share})` }}
          />
        </div>
      </div>
      <ol aria-label={t('installments.plan.list')} className="flex flex-wrap gap-1.5">
        {plan.installments.map((item) => (
          <li
            key={item.number}
            aria-label={installmentLabel(item.number, item.month, item.state)}
            data-state={item.state}
            className={cn(
              'inline-flex h-7 items-center gap-1 rounded-full border px-2 text-xs font-semibold tabular-nums',
              STATE_CLASS[item.state],
            )}
          >
            {STATE_ICON[item.state]}
            <span aria-hidden="true">
              {item.number} · {monthName(item.month).slice(0, 3)}
            </span>
          </li>
        ))}
      </ol>
      {plan.missing.length > 0 && (
        <p className="text-[13px] text-up-ink">
          {t('installments.plan.missing', { count: plan.missing.length })}
        </p>
      )}
      {owner && plan.group_id !== null && (
        <Link
          to={groupPath(plan.group_id)}
          data-testid="installment-owner"
          className={cn(
            '-mx-1 inline-flex min-h-11 items-center gap-1.5 self-start rounded-[10px] px-1 text-[13px] font-semibold text-primary no-underline hover:bg-muted',
            FOCUS,
          )}
        >
          <UsersRound size={15} aria-hidden="true" />
          {owner}
        </Link>
      )}
      <DeletePlan plan={plan} />
    </article>
  )
}

function DeletePlan({ plan }: { plan: InstallmentPlan }) {
  const [asking, setAsking] = useState(false)
  const remove = useDeleteInstallment()
  if (asking) {
    return (
      <>
        <ConfirmBox
          label={t('installments.plan.deleteLabel', { name: plan.name })}
          confirmLabel={t('installments.plan.confirmButton')}
          busy={remove.isPending}
          onConfirm={() => remove.mutate(plan.id)}
          onCancel={() => setAsking(false)}
        >
          {plan.group_name
            ? t('installments.plan.confirmGroup', { group: plan.group_name })
            : t('installments.plan.confirm')}
        </ConfirmBox>
        <Failure error={remove.error} />
      </>
    )
  }
  return (
    <div>
      <Action
        label={t('installments.plan.deleteLabel', { name: plan.name })}
        onClick={() => setAsking(true)}
      >
        {t('installments.plan.delete')}
      </Action>
    </div>
  )
}
