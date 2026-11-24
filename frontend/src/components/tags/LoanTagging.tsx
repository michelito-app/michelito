import { Checkbox } from '@/components/ui/checkbox'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { useEditLoan } from '@/lib/loanQueries'
import { useTagTarget } from '@/lib/tagQueries'
import { TagPicker } from './TagPicker'

/** On a loan: "the money reached my account" (then a tag counts the purchase, not the
 * installments) and "Add to a tag" (the whole loan, its payments come along). */
export function LoanTagging({ loan }: { loan: Loan }) {
  const edit = useEditLoan()
  const target = useTagTarget()
  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-start gap-3 text-[13px]">
        <Checkbox
          checked={loan.has_payout === true}
          disabled={edit.isPending}
          onCheckedChange={(on) => edit.mutate({ id: loan.id, body: { has_payout: on === true } })}
          className="mt-0.5"
        />
        <span className="flex flex-col gap-0.5">
          <span className="font-medium">{t('tags.loan.payout')}</span>
          <span className="text-muted-foreground">{t('tags.loan.payoutHint')}</span>
        </span>
      </label>
      <TagPicker
        label={t('tags.target.add')}
        busy={target.isPending}
        onPick={(id) => target.mutate({ id, kind: 'loans', targetId: loan.id, on: true })}
      />
    </div>
  )
}
