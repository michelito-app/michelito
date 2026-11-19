import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui/button'
import { t } from '@/i18n'
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

/** The month's "Copy for Claude": opens the dialog (the dossier is requested when it opens). What
 * was edited and pasted stays here: closing the dialog does not lose it. */
export function ClaudeButton({ month, label, selection, className }: ClaudeButtonProps) {
  const [open, setOpen] = useState(false)
  // One draft per set of accounts: the copied fingerprint is that of those accounts' dossier.
  const [drafts, setDrafts] = useState<Readonly<Record<string, ClaudeDraft>>>({})
  const scope = selectionParam(selection) ?? ''
  const draft = drafts[scope] ?? EMPTY_DRAFT
  const setDraft = (next: ClaudeDraft) => setDrafts((all) => ({ ...all, [scope]: next }))
  return (
    <>
      <Button
        variant="outline"
        aria-label={t('claude.buttonNamed', { label })}
        className={cn('h-11 rounded-xl border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2', className)}
        onClick={() => setOpen(true)}
      >
        {t('claude.button')}
      </Button>
      {/* In the body: the button may sit inside a paragraph, and the dialog has blocks. */}
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
