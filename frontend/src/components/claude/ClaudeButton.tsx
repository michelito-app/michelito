import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui/button'
import { type Selection, selectionParam } from '@/lib/accountFilter'
import { type ClaudeDraft, EMPTY_DRAFT } from '@/lib/claude'
import { cn } from '@/lib/utils'
import { ClaudeDialog } from './ClaudeDialog'

interface ClaudeButtonProps {
  month: string
  label: string
  selection: Selection
  className?: string
}

/** «Copiar para Claude» del mes: abre el diálogo (el dossier se pide al abrirlo). Lo editado y
 * pegado queda aquí: cerrar el diálogo no lo pierde. */
export function ClaudeButton({ month, label, selection, className }: ClaudeButtonProps) {
  const [open, setOpen] = useState(false)
  // Un borrador por juego de cuentas: la huella copiada es la del dossier de esas cuentas.
  const [drafts, setDrafts] = useState<Readonly<Record<string, ClaudeDraft>>>({})
  const scope = selectionParam(selection) ?? ''
  const draft = drafts[scope] ?? EMPTY_DRAFT
  const setDraft = (next: ClaudeDraft) => setDrafts((all) => ({ ...all, [scope]: next }))
  return (
    <>
      <Button
        variant="outline"
        aria-label={`Copiar para Claude ${label}`}
        className={cn('h-11 rounded-xl border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2', className)}
        onClick={() => setOpen(true)}
      >
        Copiar para Claude
      </Button>
      {/* En el cuerpo: el botón puede ir dentro de un párrafo, y el diálogo lleva bloques. */}
      {open &&
        createPortal(
          <ClaudeDialog
            month={month}
            label={label}
            selection={selection}
            draft={draft}
            onDraft={setDraft}
            onClose={() => setOpen(false)}
            onSaved={() => {
              setDraft(EMPTY_DRAFT)
              setOpen(false)
            }}
          />,
          document.body,
        )}
    </>
  )
}
