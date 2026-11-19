import type { ReactNode } from 'react'
import { useIsMobile } from '@/lib/useMobile'
import { BottomSheet } from './bottom-sheet'

interface SheetOrInlineProps {
  title: string
  onClose: () => void
  children: ReactNode
  /** Only in the sheet: what the page shows under the form anyway (an error, for example). */
  sheetExtra?: ReactNode
}

/** A long form: in place on wider screens, in a bottom sheet on a phone. */
export function SheetOrInline({ title, onClose, children, sheetExtra }: SheetOrInlineProps) {
  const mobile = useIsMobile()
  if (!mobile) return <>{children}</>
  return (
    <BottomSheet title={title} onClose={onClose}>
      {children}
      {sheetExtra}
    </BottomSheet>
  )
}
