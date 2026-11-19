// State of the "Select" mode of Transactions: the chosen ones, the visible rows, the result of
// the last batch, Esc to leave and where focus goes.
import { useCallback, useEffect, useRef, useState } from 'react'
import { t } from '@/i18n'
import type { Tx } from './api'
import { pruned, toggled } from './selection'

/** Marker of the action bar (for Esc and focus). */
export const BAR_ATTR = 'data-selection-bar'
const LIST_CHECKBOX = `section[aria-label="${t('common.transactionListLabel')}"] input[type="checkbox"]`
const TYPING = 'input, select, textarea'

export interface BatchNote {
  text: string
  entryId: number | null // the log entry; null if nothing changed
}

export interface TxSelection {
  chosen: ReadonlySet<string> | null // null: outside the mode
  visible: readonly string[] // the visible rows (with groups, those of the open ones)
  note: BatchNote | null
  start: () => void
  /** Enters the mode with this row already chosen (the phone's long-press); focus goes to it. */
  startWith: (tx: Tx) => void
  cancel: () => void
  toggle: (tx: Tx) => void
  selectVisible: () => void
  onVisible: (fingerprints: string[]) => void
  done: (note: BatchNote) => void
  dismissNote: () => void
}

/** `items`: the current list (undefined while loading). When it changes, the chosen ones no
 * longer there are dropped (they do not come back when the filter is removed). */
export function useTxSelection(items: readonly Tx[] | undefined): TxSelection {
  const [chosen, setChosen] = useState<ReadonlySet<string> | null>(null)
  const [visible, setVisible] = useState<readonly string[]>([])
  const [note, setNote] = useState<BatchNote | null>(null)
  // Where focus goes on entering: the first checkbox (true), a row's (its fingerprint) or nowhere.
  const focusList = useRef<boolean | string>(false)
  const picking = chosen !== null

  // When another list arrives (filters), those that left are dropped (during render, no effect).
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
      // In a field of the bar, Esc belongs to the field (close the select, stop typing).
      if (target instanceof Element && target.closest(`[${BAR_ATTR}]`) && target.matches(TYPING)) {
        return
      }
      setChosen(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picking])

  // On entering, focus goes to the first checkbox (or, without any, to the bar).
  useEffect(() => {
    if (!picking || !focusList.current) return
    const target = focusList.current
    focusList.current = false
    if (typeof target === 'string') {
      const row = document.querySelector<HTMLElement>(
        `[data-fingerprint="${CSS.escape(target)}"] input[type="checkbox"]`,
      )
      row?.focus({ preventScroll: true })
      return
    }
    const first = document.querySelector<HTMLElement>(LIST_CHECKBOX)
    const bar = document.querySelector<HTMLElement>(`[${BAR_ATTR}]`)
    ;(first ?? bar)?.focus()
  }, [picking])

  const start = useCallback(() => {
    focusList.current = true
    setNote(null)
    setChosen(new Set())
  }, [])
  const startWith = useCallback((tx: Tx) => {
    focusList.current = tx.fingerprint
    setNote(null)
    setChosen(new Set([tx.fingerprint]))
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
    startWith,
    cancel,
    toggle,
    selectVisible,
    onVisible: setVisible,
    done,
    dismissNote,
  }
}
