import { Clock, ShieldAlert } from 'lucide-react'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'

/** In the detail: the movement comes from a bank alert and its statement has not arrived yet.
 * It counts like any other; the statement confirms it (keeping the edits) when it arrives. */
export function ProvisionalNote({ tx }: { tx: Tx }) {
  const approved = tx.approved ? <ApprovedNote /> : null
  if (!tx.provisional) return approved
  return (
    <>
      <Pending />
      {approved}
    </>
  )
}

function Pending() {
  return (
    <p
      data-testid="provisional-note"
      className="flex items-start gap-1.5 rounded-xl bg-[#FFF6E5] px-3 py-2 text-[13px] text-[#7A4B00] dark:bg-[#3A2A0A] dark:text-[#F5C97A]"
    >
      <Clock size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
      <span>
        <strong className="font-semibold">{t('transactions.provisional.title')}</strong>{' '}
        {t('transactions.provisional.detail')}
      </span>
    </p>
  )
}

/** In the detail (hosted): it entered because the person approved an email that could not be
 * verified as the bank's; it can be taken back in Settings. */
function ApprovedNote() {
  return (
    <p
      data-testid="approved-note"
      className="flex items-start gap-1.5 rounded-xl bg-[#FDECEC] px-3 py-2 text-[13px] text-[#8A1F1F] dark:bg-[#3A1414] dark:text-[#F5A3A3]"
    >
      <ShieldAlert size={15} aria-hidden="true" className="mt-0.5 shrink-0" />
      <span>{t('forwarding.badge.approvedDetail')}</span>
    </p>
  )
}
