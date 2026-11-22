import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { currentOpener } from '@/lib/opener'
import { lockScroll } from '@/lib/scrollLock'
import { cn } from '@/lib/utils'

interface BottomSheetProps {
  title: string
  onClose: () => void
  children: ReactNode
  /** Extra classes for the content area. */
  className?: string
  /** On a phone it takes the whole screen (a long form). */
  full?: boolean
}

/** Modal sheet that rises from the bottom (native `<dialog>`, like `Modal`): focus is trapped
 * and returned to the opener, Escape and a tap outside close it, the background is inert. It
 * opens when mounted; the caller unmounts it to close it. The page behind does not scroll while it
 * is open. No drag gestures. */
export function BottomSheet({ title, onClose, children, className, full }: BottomSheetProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    const opener = currentOpener()
    if (dialog && !dialog.open) dialog.showModal()
    const unlock = lockScroll()
    return () => {
      unlock()
      dialog?.close()
      if (opener?.isConnected) opener.focus({ preventScroll: true })
    }
  }, [])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-modal="true"
      data-bottom-sheet=""
      onCancel={(event) => {
        // A sheet opened from inside this one (nested in its tree) handles its own Escape.
        if (event.target !== event.currentTarget) return
        event.preventDefault()
        onClose()
      }}
      // The dialog itself only receives the click on its backdrop (the content fills it).
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className={cn(
        'mx-0 mt-auto mb-0 flex max-h-[90dvh] w-full max-w-none flex-col overflow-hidden rounded-t-2xl border border-b-0 border-border bg-card p-0 text-foreground shadow-[0_-8px_32px_rgba(27,29,33,0.16)] backdrop:bg-black/30 not-open:hidden md:mx-auto md:max-w-[560px]',
        full && 'max-md:h-dvh max-md:max-h-dvh max-md:rounded-none max-md:border-0',
      )}
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-1.5">
        <h2 id={titleId} className="min-w-0 text-[16px] font-[650] tracking-tight">
          {title}
        </h2>
        <button
          type="button"
          aria-label={t('common.close')}
          onClick={onClose}
          className={cn(
            '-mr-2 flex size-11 shrink-0 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-muted',
            FOCUS,
          )}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      <div
        className={cn(
          'flex min-h-0 flex-col gap-4 overflow-y-auto overscroll-contain px-4 pt-4 pb-[max(16px,env(safe-area-inset-bottom))]',
          className,
        )}
      >
        {children}
      </div>
    </dialog>
  )
}
