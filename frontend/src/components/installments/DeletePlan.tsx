import { useState } from 'react'
import { Action, ConfirmBox, Failure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { InstallmentPlan } from '@/lib/api'
import { useDeleteInstallment } from '@/lib/installmentQueries'

/** "Delete plan", with a confirmation: the charges go back to being loose expenses. */
export function DeletePlan({ plan, onDeleted }: { plan: InstallmentPlan; onDeleted: () => void }) {
  const [asking, setAsking] = useState(false)
  const remove = useDeleteInstallment()
  if (asking) {
    return (
      <>
        <ConfirmBox
          label={t('installments.plan.deleteLabel', { name: plan.name })}
          confirmLabel={t('installments.plan.confirmButton')}
          busy={remove.isPending}
          onConfirm={() => remove.mutate(plan.id, { onSuccess: onDeleted })}
          onCancel={() => setAsking(false)}
        >
          {plan.contact_name
            ? t('installments.plan.confirmPerson', { contact: plan.contact_name })
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
