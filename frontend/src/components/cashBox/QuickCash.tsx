import { Plus } from 'lucide-react'
import { useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { Modal } from '@/components/ui/modal'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { localToday } from '@/lib/cashBox'
import { useCashBox } from '@/lib/queries'
import { useIsMobile } from '@/lib/useMobile'
import { cn } from '@/lib/utils'
import { CashEntryForm } from './CashEntryForm'

/** The cash "+": on a phone it floats above the bottom bar; on a wider screen it is a header
 * button. It opens "I spent cash / I received cash" (amount, concept, date, "Repeat"). */
export function QuickCashButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-label={t('cashBox.quick.label')}
        onClick={() => setOpen(true)}
        data-quick-cash=""
        className={cn(
          'inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-xl md:ml-auto bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/85',
          'max-md:fixed max-md:right-4 max-md:bottom-[calc(var(--bottom-bar)+env(safe-area-inset-bottom)+12px)] max-md:z-30 max-md:min-h-12 max-md:rounded-full max-md:px-5 max-md:shadow-[0_6px_20px_rgba(27,29,33,0.22)]',
          FOCUS,
        )}
      >
        <Plus size={18} aria-hidden="true" />
        {t('cashBox.quick.button')}
      </button>
      {open && <QuickCashDialog onClose={() => setOpen(false)} />}
    </>
  )
}

/** Room at the end of a phone page for the floating «+»: the last card's links scroll clear of
 * it (it sits above the bottom bar). Nothing on a wider screen. */
export function FabSpace() {
  return <div aria-hidden="true" className="h-14 shrink-0 md:hidden" />
}

function QuickCashDialog({ onClose }: { onClose: () => void }) {
  const mobile = useIsMobile()
  const box = useCashBox()
  const body = box.data ? (
    <CashEntryForm
      kind="expense"
      box={box.data}
      today={localToday()}
      switchable
      untitled
      onDone={onClose}
    />
  ) : (
    <Skeleton className="h-64 rounded-xl" />
  )
  if (mobile) {
    return (
      <BottomSheet title={t('cashBox.quick.title')} onClose={onClose} full>
        {body}
      </BottomSheet>
    )
  }
  return (
    <Modal title={t('cashBox.quick.title')} onClose={onClose}>
      {body}
    </Modal>
  )
}
