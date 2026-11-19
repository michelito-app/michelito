import { useEffect, useRef, useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/modal'
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
  /** «Febrero 2026». */
  label: string
  /** Las cuentas de la pantalla: el dossier y el análisis guardado van con ellas. */
  selection: Selection
  /** Lo editado y pegado: vive en quien abre el diálogo, para no perderlo al cerrarlo. */
  draft: ClaudeDraft
  onDraft: (draft: ClaudeDraft) => void
  onClose: () => void
  /** Guardado: quien abre el diálogo limpia el borrador y lo cierra. */
  onSaved: () => void
}

/** «Copiar para Claude»: la instrucción (editable, con «Restablecer») y el dossier del mes van
 * al portapapeles; luego se pega aquí la respuesta y se guarda como el análisis del mes. Si el
 * portapapeles falla, el texto queda seleccionado en un campo de solo lectura. */
export function ClaudeDialog(props: ClaudeDialogProps) {
  const { month, label, selection, draft, onDraft, onClose, onSaved } = props
  const mode = useMode()
  const instruction = useClaudeInstruction()
  const dossier = useDossier(month, selection)
  const saved = useInsight(month)
  const accounts = useAccounts()
  const save = useSavePastedInsight()
  const [copied, setCopied] = useState<'no' | 'copiado' | 'manual'>('no')
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
    // El análisis que se pegue es de este dossier: se guarda con su huella.
    onDraft({ ...draft, huella: dossier.data.huella })
    if (isDemo(mode)) countEvent(COPY_EVENT)
  }

  function submit() {
    if (!canSave(answer)) return
    if (existing && !confirming) {
      setConfirming(true)
      return
    }
    const huella = draft.huella ?? dossier.data?.huella ?? null
    save.mutate({ month, text: answer, selection, huella }, { onSuccess: onSaved })
  }

  const left = remaining(answer)
  return (
    <Modal title={`Copiar para Claude · ${label}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Instrucción para Claude
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
          Restablecer
        </Button>
        <p className="text-[13px] text-muted-foreground">
          {dossier.isError
            ? `No se pudo cargar el dossier: ${dossier.error.message}`
            : dossier.isSuccess
              ? `Dossier de ${label}: ${sizeText(dossier.data.markdown)}. Las cuentas son las de esta pantalla.`
              : 'Cargando el dossier…'}
        </p>
        {instruction.isError && (
          <p role="alert" className="text-[13px] text-destructive">
            No se pudo cargar la instrucción: {instruction.error.message}
          </p>
        )}
        <Button className={cn(BUTTON, 'self-start')} disabled={!ready} onClick={() => void copy()}>
          {copied === 'copiado' ? 'Copiado' : 'Copiar'}
        </Button>
        {copied === 'copiado' && (
          <p role="status" className="text-[13px] text-ink-2">
            Instrucción y dossier copiados.
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
              aria-label="Texto para copiar a mano"
              className={cn(AREA, 'font-mono text-xs md:text-xs')}
            />
          </>
        )}
        <p className="text-[13px] text-muted-foreground">{HELP}.</p>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Respuesta de Claude (Markdown)
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
          {left < 0 ? `Sobran ${-left} caracteres` : `Quedan ${left} caracteres`}
        </p>
        {save.error && (
          <p role="alert" className="text-[13px] text-destructive">
            No se pudo guardar: {save.error.message}
          </p>
        )}
        {existing && (
          <p className="text-[13px] font-semibold text-up">
            Reemplaza el análisis guardado (cuentas: {accountsText(existing.accounts, labels)})
          </p>
        )}
        {confirming ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="text-[13px] text-ink-2">¿Reemplazar el análisis de {label}?</span>
            <Button className={BUTTON} disabled={save.isPending} onClick={submit}>
              Sí, reemplazar
            </Button>
            <Button variant="outline" className={BUTTON} onClick={() => setConfirming(false)}>
              No
            </Button>
          </div>
        ) : (
          <Button className={cn(BUTTON, 'self-end')} disabled={!canSave(answer) || save.isPending} onClick={submit}>
            Guardar análisis
          </Button>
        )}
      </div>
    </Modal>
  )
}
