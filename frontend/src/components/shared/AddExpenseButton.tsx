import { Plus } from 'lucide-react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { cn } from '@/lib/utils'

/** "+ Add expense": on a phone it floats above the bottom bar (right side, clear of the bar;
 * the demo notice and its feedback button live in the header at the top); on a wider screen it
 * is a header button. */
export function AddExpenseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-haspopup="dialog"
      onClick={onClick}
      data-add-expense=""
      className={cn(
        'inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/85',
        'max-md:fixed max-md:right-4 max-md:bottom-[calc(var(--bottom-bar)+env(safe-area-inset-bottom)+12px)] max-md:z-30 max-md:min-h-12 max-md:rounded-full max-md:px-5 max-md:shadow-[0_6px_20px_rgba(27,29,33,0.22)]',
        FOCUS,
      )}
    >
      <Plus size={18} aria-hidden="true" />
      {t('shared.addExpense')}
    </button>
  )
}
