import { useState } from 'react'
import { Action, ConfirmBox, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { Loan } from '@/lib/api'
import { useDeleteLoan } from '@/lib/loanQueries'

/** "Delete loan", with a confirmation: the payments stay as they are. */
export function DeleteLoan({ loan, onDeleted }: { loan: Loan; onDeleted: () => void }) {
  const [asking, setAsking] = useState(false)
  const remove = useDeleteLoan()
  const label = t('loans.delete.label', { name: loan.name })
  if (asking) {
    return (
      <>
        <ConfirmBox
          label={label}
          confirmLabel={t('loans.delete.confirmButton')}
          busy={remove.isPending}
          onConfirm={() => remove.mutate(loan.id, { onSuccess: onDeleted })}
          onCancel={() => setAsking(false)}
        >
          {t('loans.delete.confirm')}
        </ConfirmBox>
        <Failure error={remove.error} />
      </>
    )
  }
  return (
    <div>
      <Action label={label} onClick={() => setAsking(true)}>
        {t('loans.delete.action')}
      </Action>
    </div>
  )
}
