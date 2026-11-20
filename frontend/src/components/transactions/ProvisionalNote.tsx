import { Clock } from 'lucide-react'
import { t } from '@/i18n'
import type { Tx } from '@/lib/api'

/** In the detail: the movement comes from a bank alert and its statement has not arrived yet.
 * It counts like any other; the statement confirms it (keeping the edits) when it arrives. */
export function ProvisionalNote({ tx }: { tx: Tx }) {
  if (!tx.provisional) return null
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
