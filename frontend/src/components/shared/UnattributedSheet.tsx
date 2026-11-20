import { Failure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import { formatMoney } from '@/lib/links'
import { shortDay } from '@/lib/months'
import type { Group } from '@/lib/sharedApi'
import { ledger, useLedgerWrite } from '@/lib/sharedQueries'
import { Chip } from './parts'
import { LIST_CARD } from './styles'

/** "Assign": each unattributed payment with one chip per person; one tap assigns it. */
export function UnattributedSheet({ group, onClose }: { group: Group; onClose: () => void }) {
  const write = useLedgerWrite()
  const others = group.members.filter((m) => !m.is_me)
  const left = group.unattributed
  return (
    <BottomSheet title={t('shared.unattributed.title')} onClose={onClose}>
      <p className="text-[13px] text-muted-foreground">{t('shared.unattributed.hint')}</p>
      <ul className={LIST_CARD}>
        {left.map((payment) => (
          <li key={payment.id} className="flex flex-col gap-2 px-3.5 py-3">
            <span className="text-sm font-semibold">
              {shortDay(payment.day)} · {formatMoney(payment.amount_cents, payment.currency)}
              {payment.transaction ? ` · ${payment.transaction.merchant}` : ''}
            </span>
            <div className="flex flex-wrap gap-2">
              {others.map((member) => (
                <Chip
                  key={member.id}
                  on={false}
                  onClick={() =>
                    write.mutate(() => ledger.patchPayment(payment.id, { from_contact: member.id }), {
                      onSuccess: (fresh) => {
                        if (fresh.unattributed.length === 0) onClose()
                      },
                    })
                  }
                >
                  {t('shared.unattributed.from', { name: member.name })}
                </Chip>
              ))}
            </div>
          </li>
        ))}
      </ul>
      <Failure error={write.error} />
    </BottomSheet>
  )
}
