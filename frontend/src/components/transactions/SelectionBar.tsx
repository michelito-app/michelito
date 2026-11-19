import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { FOCUS } from '@/components/summary/styles'
import { categoryGroups } from '@/lib/categories'
import type { Category, Tx } from '@/lib/api'
import { REASON_MAX } from '@/lib/log'
import { useBatchCategory } from '@/lib/queries'
import { BATCH_MAX, batchOptions, counterText, linkedText, resultText } from '@/lib/selection'
import { BAR_ATTR, type BatchNote } from '@/lib/useTxSelection'
import { cn } from '@/lib/utils'
import { ReserveBatch } from './ReserveBatch'

const NONE = ''
const CONTROL = cn(
  'h-11 min-w-0 rounded-xl border border-border bg-card px-3 text-sm text-foreground',
  FOCUS,
)
const ACTION = cn('h-11 shrink-0 rounded-xl px-4 text-sm font-semibold', FOCUS)

interface SelectionBarProps {
  /** Las elegidas que se ven con los filtros de ahora. */
  chosen: Tx[]
  /** Cuántas filas se ven (con grupos, las de los abiertos): «Seleccionar todo lo visible». */
  visible: number
  /** ¿Ya están elegidas todas las que se ven? (entonces no hace falta el botón). */
  allVisibleChosen: boolean
  categories: readonly Category[]
  onSelectAll: () => void
  onCancel: () => void
  /** Terminó: el resultado (lo dice la página al salir del modo). */
  onDone: (note: BatchNote) => void
}

/** Barra fija abajo del modo «Seleccionar»: contador, «Seleccionar todo lo visible», la
 * categoría nueva (solo esas transacciones) y un motivo común. Deja debajo de la lista un hueco
 * de su alto, así nunca tapa la última fila. */
export function SelectionBar({
  chosen,
  visible,
  allVisibleChosen,
  categories,
  onSelectAll,
  onCancel,
  onDone,
}: SelectionBarProps) {
  const bar = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(0)
  const left = useMainLeft()
  const [categoryId, setCategoryId] = useState(NONE)
  const [reason, setReason] = useState('')
  const batch = useBatchCategory()
  const options = batchOptions(categories, chosen)
  const target = options.categories.find((c) => String(c.id) === categoryId) ?? null
  const linked = linkedText(chosen)
  const tooMany = chosen.length > BATCH_MAX

  useEffect(() => {
    const node = bar.current
    if (!node) return
    const observer = new ResizeObserver(() => setHeight(node.offsetHeight))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  function apply() {
    if (!target || chosen.length === 0 || tooMany) return
    batch.mutate(
      {
        fingerprints: chosen.map((t) => t.fingerprint),
        category_id: target.id,
        reason: reason.trim(),
      },
      {
        onSuccess: (result) =>
          onDone({ text: resultText(result, target.name), entryId: result.entry_id }),
      },
    )
  }

  const groups = categoryGroups(options.categories)
  return (
    <>
      <div aria-hidden="true" style={{ height }} />
      <div
        ref={bar}
        role="region"
        aria-label="Acciones de la selección"
        tabIndex={-1}
        {...{ [BAR_ATTR]: '' }}
        style={{ left }}
        className="fixed right-0 bottom-0 z-30 border-t border-border bg-card px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] shadow-[0_-8px_24px_rgba(27,29,33,0.12)] outline-none sm:px-10"
      >
        <div className="mx-auto flex max-w-[1400px] flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-sm font-semibold tabular-nums" aria-live="polite">
              {counterText(chosen)}
            </span>
            {visible > 0 && !allVisibleChosen && (
              <button
                type="button"
                onClick={onSelectAll}
                className={cn('min-h-11 rounded-md px-1 text-[13px] font-semibold text-primary', FOCUS)}
              >
                Seleccionar todo lo visible ({visible})
              </button>
            )}
          </div>
          {(options.notice || linked || tooMany) && (
            <p className="text-[13px] text-ink-2">
              {[options.notice, linked, tooMany ? `Como mucho ${BATCH_MAX} a la vez.` : null]
                .filter(Boolean)
                .join(' ')}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Nueva categoría"
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
              className={cn(CONTROL, 'flex-[1_1_200px] font-semibold')}
            >
              <option value={NONE}>Cambiar categoría a…</option>
              {groups.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.names.map((name) => {
                    const found = options.categories.find((c) => c.name === name)
                    return found ? (
                      <option key={found.id} value={String(found.id)}>
                        {name}
                      </option>
                    ) : null
                  })}
                </optgroup>
              ))}
            </select>
            <input
              type="text"
              aria-label="Motivo (opcional)"
              placeholder="Motivo (opcional)"
              maxLength={REASON_MAX}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={cn(CONTROL, 'flex-[2_1_220px]')}
            />
            <div className="flex flex-[1_0_auto] justify-end gap-2">
              <button
                type="button"
                onClick={onCancel}
                className={cn(ACTION, 'border border-border bg-card text-foreground hover:bg-muted')}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={apply}
                disabled={!target || chosen.length === 0 || tooMany || batch.isPending}
                className={cn(
                  ACTION,
                  'bg-primary text-primary-foreground hover:bg-primary/85 disabled:opacity-50',
                )}
              >
                {batch.isPending ? 'Cambiando…' : 'Cambiar categoría'}
              </button>
            </div>
          </div>
          {batch.isError && (
            <p role="alert" className="text-[13px] font-semibold text-up">
              No se pudo cambiar: {batch.error.message}
            </p>
          )}
          <ReserveBatch chosen={chosen} onDone={onDone} />
        </div>
      </div>
    </>
  )
}

/** Dónde empieza `main` (a la derecha del menú lateral; 0 cuando el menú va arriba): la barra
 * se alinea con el contenido y no tapa el menú. */
function useMainLeft(): number {
  const [left, setLeft] = useState(0)
  useEffect(() => {
    const main = document.querySelector('main')
    if (!main) return
    const measure = () => setLeft(Math.max(0, main.getBoundingClientRect().left))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(main)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [])
  return left
}

interface BatchNoticeProps {
  note: BatchNote
  onClose: () => void
}

/** El resultado del último lote. Recibe el foco al aparecer; «Ver en la Bitácora» solo si quedó
 * una entrada. */
export function BatchNotice({ note, onClose }: BatchNoticeProps) {
  const box = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    box.current?.focus()
  }, [note])
  return (
    <p
      ref={box}
      role="status"
      tabIndex={-1}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-primary/30 bg-[#F6FAF8] px-4 py-2.5 text-sm text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
    >
      <span>{note.text}</span>
      {note.entryId !== null && (
        <Link to="/bitacora" className="font-semibold text-primary">
          Ver en la Bitácora
        </Link>
      )}
      <button
        type="button"
        onClick={onClose}
        className={cn(
          'ml-auto min-h-11 rounded-md px-2 text-[13px] font-semibold text-muted-foreground hover:text-foreground',
          FOCUS,
        )}
      >
        Cerrar
      </button>
    </p>
  )
}
