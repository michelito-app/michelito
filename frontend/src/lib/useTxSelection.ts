// Estado del modo «Seleccionar» de Transacciones: las elegidas, las filas que se ven, el
// resultado del último lote, Esc para salir y adónde va el foco.
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Tx } from './api'
import { pruned, toggled } from './selection'

/** Marca de la barra de acciones (para Esc y el foco). */
export const BAR_ATTR = 'data-selection-bar'
const LIST_CHECKBOX = 'section[aria-label="Lista de transacciones"] input[type="checkbox"]'
const TYPING = 'input, select, textarea'

export interface BatchNote {
  text: string
  entryId: number | null // la entrada de la bitácora; null si nada cambió
}

export interface TxSelection {
  chosen: ReadonlySet<string> | null // null: fuera del modo
  visible: readonly string[] // las filas que se ven (con grupos, las de los abiertos)
  note: BatchNote | null
  start: () => void
  cancel: () => void
  toggle: (tx: Tx) => void
  selectVisible: () => void
  onVisible: (fingerprints: string[]) => void
  done: (note: BatchNote) => void
  dismissNote: () => void
}

/** `items`: la lista de ahora (undefined mientras carga). Al cambiar, las elegidas que ya no
 * están se sueltan (no vuelven al quitar el filtro). */
export function useTxSelection(items: readonly Tx[] | undefined): TxSelection {
  const [chosen, setChosen] = useState<ReadonlySet<string> | null>(null)
  const [visible, setVisible] = useState<readonly string[]>([])
  const [note, setNote] = useState<BatchNote | null>(null)
  const focusList = useRef(false)
  const picking = chosen !== null

  // Al llegar otra lista (filtros), se sueltan las que salieron (durante el render, sin efecto).
  const [seen, setSeen] = useState(items)
  if (items !== seen) {
    setSeen(items)
    const next = items && chosen ? pruned(chosen, items) : chosen
    if (next !== chosen) setChosen(next)
  }

  useEffect(() => {
    if (!picking) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      const target = event.target
      // En un campo de la barra, Esc es del campo (cerrar el selector, dejar de escribir).
      if (target instanceof Element && target.closest(`[${BAR_ATTR}]`) && target.matches(TYPING)) {
        return
      }
      setChosen(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picking])

  // Al entrar, el foco va a la primera casilla (o, sin ninguna, a la barra).
  useEffect(() => {
    if (!picking || !focusList.current) return
    focusList.current = false
    const first = document.querySelector<HTMLElement>(LIST_CHECKBOX)
    const bar = document.querySelector<HTMLElement>(`[${BAR_ATTR}]`)
    ;(first ?? bar)?.focus()
  }, [picking])

  const start = useCallback(() => {
    focusList.current = true
    setNote(null)
    setChosen(new Set())
  }, [])
  const cancel = useCallback(() => setChosen(null), [])
  const toggle = useCallback(
    (tx: Tx) => setChosen((current) => toggled(current ?? new Set(), tx.fingerprint)),
    [],
  )
  const selectVisible = useCallback(
    () => setChosen((current) => new Set([...(current ?? []), ...visible])),
    [visible],
  )
  const done = useCallback((result: BatchNote) => {
    setChosen(null)
    setNote(result)
  }, [])
  const dismissNote = useCallback(() => setNote(null), [])
  return {
    chosen,
    visible,
    note,
    start,
    cancel,
    toggle,
    selectVisible,
    onVisible: setVisible,
    done,
    dismissNote,
  }
}
