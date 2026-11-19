import { useEffect, useRef, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import {
  accountsText,
  browserClipboard,
  type ClaudeDraft,
  COPY_EVENT,
  composeForClaude,
  copyText,
  HELP,
  MANUAL_NOTE,
  sizeText,
} from '@/lib/claude'
import { countEvent, isDemo, useMode } from '@/lib/demo'
import { canSave, remaining } from '@/lib/insights'
import { useAccounts, useClaudeInstruction, useDossier, useInsight, useSavePastedInsight } from '@/lib/queries'
import { cn } from '@/lib/utils'

const AREA = cn(
  'w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base font-normal md:text-sm',
  FOCUS,
)
const BUTTON = 'h-11 px-4 text-sm font-semibold'

export interface ClaudeDialogProps {
  month: string
  /** The month's title, e.g. "<Month> 2026". */
  label: string
  /** The screen's accounts: the dossier and the saved analysis go with them. */
  selection: Selection
  /** What was edited and pasted: it lives in whoever opens the dialog, so closing loses nothing. */
  draft: ClaudeDraft
  onDraft: (draft: ClaudeDraft) => void
  onClose: () => void
  /** Saved: whoever opens the dialog clears the draft and closes it. */
  onSaved: () => void
}

/** "Copy for Claude": the instruction (editable, with a reset) and the month's dossier go to the
 * clipboard; then the answer is pasted here and saved as the month's analysis. When the
 * clipboard fails, the text is left selected in a read-only field. */
export function ClaudeDialog(props: ClaudeDialogProps) {
  const { month, label, selection, draft, onDraft, onClose, onSaved } = props
  const mode = useMode()
  const instruction = useClaudeInstruction()
  const dossier = useDossier(month, selection)
  const saved = useInsight(month)
  const accounts = useAccounts()
  const save = useSavePastedInsight()
  const [copied, setCopied] = useState<'no' | 'copied' | 'manual'>('no')
  const [manual, setManual] = useState('')
  const [confirming, setConfirming] = useState(false)
  const manualRef = useRef<HTMLTextAreaElement>(null)
  const original = instruction.data ?? ''
  const text = draft.instruction ?? original
  const answer = draft.answer
  const ready = instruction.isSuccess && dossier.isSuccess
  const existing = saved.data ?? null
  const labels = new Map((accounts.data ?? []).map((account) => [account.key, account.label]))

  useEffect(() => {
    if (copied !== 'manual') return
    manualRef.current?.focus()
    manualRef.current?.select()
  }, [copied, manual])

  async function copy() {
    if (!dossier.data) return
    const full = composeForClaude(text, dossier.data.markdown)
    const result = await copyText(full, browserClipboard())
    setManual(result === 'manual' ? full : '')
    setCopied(result)
    // The analysis pasted next is about this dossier: it is saved with its fingerprint.
    onDraft({ ...draft, fingerprint: dossier.data.fingerprint })
    if (isDemo(mode)) countEvent(COPY_EVENT)
  }

  function submit() {
    if (!canSave(answer)) return
    if (existing && !confirming) {
      setConfirming(true)
      return
    }
    const fingerprint = draft.fingerprint ?? dossier.data?.fingerprint ?? null
    save.mutate({ month, text: answer, selection, fingerprint }, { onSuccess: onSaved })
  }

  const left = remaining(answer)
  return (
    <Modal title={t('claude.dialog.title', { label })} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          {t('claude.dialog.instruction')}
          <textarea
            value={text}
            rows={6}
            disabled={!instruction.isSuccess}
            onChange={(event) => onDraft({ ...draft, instruction: event.target.value })}
            className={AREA}
          />
        </label>
        <Button
          variant="outline"
          className={cn(BUTTON, 'self-start')}
          disabled={draft.instruction === null || draft.instruction === original}
          onClick={() => onDraft({ ...draft, instruction: null })}
        >
          {t('claude.dialog.reset')}
        </Button>
        <p className="text-[13px] text-muted-foreground">
          {dossier.isError
            ? t('claude.dialog.dossierFailed', { message: dossier.error.message })
            : dossier.isSuccess
              ? t('claude.dialog.dossierSize', { label, size: sizeText(dossier.data.markdown) })
              : t('claude.dialog.dossierLoading')}
        </p>
        {instruction.isError && (
          <p role="alert" className="text-[13px] text-destructive">
            {t('claude.dialog.instructionFailed', { message: instruction.error.message })}
          </p>
        )}
        <Button className={cn(BUTTON, 'self-start')} disabled={!ready} onClick={() => void copy()}>
          {copied === 'copied' ? t('claude.dialog.copied') : t('claude.dialog.copy')}
        </Button>
        {copied === 'copied' && (
          <p role="status" className="text-[13px] text-ink-2">
            {t('claude.dialog.copiedNote')}
          </p>
        )}
        {copied === 'manual' && (
          <>
            <p role="status" className="text-[13px] text-ink-2">
              {MANUAL_NOTE}
            </p>
            <textarea
              ref={manualRef}
              readOnly
              value={manual}
              rows={4}
              aria-label={t('claude.dialog.manualText')}
              className={cn(AREA, 'font-mono text-xs md:text-xs')}
            />
          </>
        )}
        <p className="text-[13px] text-muted-foreground">{t('claude.dialog.helpLine', { help: HELP })}</p>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          {t('claude.dialog.answer')}
          <textarea
            value={answer}
            rows={5}
            onChange={(event) => {
              setConfirming(false)
              onDraft({ ...draft, answer: event.target.value })
            }}
            className={AREA}
          />
        </label>
        <p className={cn('-mt-2 text-[12px]', left < 0 ? 'font-semibold text-up' : 'text-muted-foreground')}>
          {left < 0
            ? t('claude.dialog.over', { count: -left })
            : t('claude.dialog.left', { count: left })}
        </p>
        {save.error && (
          <p role="alert" className="text-[13px] text-destructive">
            {t('claude.dialog.saveFailed', { message: save.error.message })}
          </p>
        )}
        {existing && (
          <p className="text-[13px] font-semibold text-up">
            {t('claude.dialog.replaces', { accounts: accountsText(existing.accounts, labels) })}
          </p>
        )}
        {confirming ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="text-[13px] text-ink-2">{t('claude.dialog.confirm', { label })}</span>
            <Button className={BUTTON} disabled={save.isPending} onClick={submit}>
              {t('claude.dialog.yesReplace')}
            </Button>
            <Button variant="outline" className={BUTTON} onClick={() => setConfirming(false)}>
              {t('claude.dialog.no')}
            </Button>
          </div>
        ) : (
          <Button className={cn(BUTTON, 'self-end')} disabled={!canSave(answer) || save.isPending} onClick={submit}>
            {t('claude.dialog.save')}
          </Button>
        )}
      </div>
    </Modal>
  )
}
