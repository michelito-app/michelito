import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { cn } from '@/lib/utils'

interface ModalProps {
  title: string
  onClose: () => void
  children: ReactNode
}

/** Native modal dialog (`<dialog>`): traps focus, Escape closes it and the background is inert.
 * It opens when mounted; the caller unmounts it to close it, and focus returns to what was
 * focused when it opened (if still on the page). */
export function Modal({ title, onClose, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    // On close, focus returns to what opened it (on unmount `close()` no longer returns it: the
    // dialog has left the document).
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (dialog && !dialog.open) dialog.showModal()
    return () => {
      dialog?.close()
      if (opener?.isConnected) opener.focus()
    }
  }, [])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      className="m-auto w-[min(440px,calc(100vw-32px))] max-w-none rounded-2xl border border-border bg-card p-0 text-foreground shadow-xl backdrop:bg-black/30"
    >
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-[17px] font-[650] tracking-tight">
            {title}
          </h2>
          <button
            type="button"
            aria-label={t('common.close')}
            onClick={onClose}
            className={cn(
              '-mt-2 -mr-2 flex size-11 shrink-0 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-muted',
              FOCUS,
            )}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  )
}
