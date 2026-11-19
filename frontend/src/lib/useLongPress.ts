// Long-press on a list row (the phone's way into "Select"): holding still for LONG_PRESS_MS fires
// it, and the click that follows the release is swallowed (wherever it lands: the row may have
// been replaced by its selection version). Moving the finger (scrolling) cancels.
import { type MouseEvent, type PointerEvent, useEffect, useRef } from 'react'

export const LONG_PRESS_MS = 500
/** Movement (px) that turns the press into a scroll. */
const SLOP = 10

export interface LongPressHandlers {
  onPointerDown: (event: PointerEvent) => void
  onPointerMove: (event: PointerEvent) => void
  onPointerUp: () => void
  onPointerCancel: () => void
  onPointerLeave: () => void
  onContextMenu: (event: MouseEvent) => void
}

/** Handlers for an element; `onLongPress` null disables them (returns null). */
export function useLongPress(onLongPress: (() => void) | null): LongPressHandlers | null {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const fired = useRef(false)
  const callback = useRef(onLongPress)
  useEffect(() => {
    callback.current = onLongPress
  })
  // Unmounting mid-press (the list changed) drops the pending timer.
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current)
    },
    [],
  )

  function clear() {
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
    start.current = null
  }

  if (onLongPress === null) return null
  return {
    onPointerDown(event) {
      if (event.button !== 0) return
      clear()
      fired.current = false
      start.current = { x: event.clientX, y: event.clientY }
      timer.current = setTimeout(() => {
        timer.current = null
        fired.current = true
        swallowNextClick()
        callback.current?.()
      }, LONG_PRESS_MS)
    },
    onPointerMove(event) {
      const from = start.current
      if (from && Math.hypot(event.clientX - from.x, event.clientY - from.y) > SLOP) clear()
    },
    onPointerUp() {
      clear()
      fired.current = false
    },
    onPointerCancel: clear,
    onPointerLeave: clear,
    onContextMenu(event) {
      // The browser's own long-press menu would cover the selection.
      if (timer.current !== null || fired.current) event.preventDefault()
    },
  }
}

/** The click that ends a long press does nothing (it is caught before reaching any element). It
 * stops waiting shortly after the finger lifts: a release without a click (a cancelled touch) must
 * not eat a later tap. */
function swallowNextClick() {
  const stop = () => window.removeEventListener('click', swallow, true)
  const swallow = (event: Event) => {
    event.preventDefault()
    event.stopPropagation()
    stop()
  }
  const released = () => {
    window.removeEventListener('pointerup', released, true)
    window.removeEventListener('pointercancel', released, true)
    setTimeout(stop, 400)
  }
  window.addEventListener('click', swallow, true)
  window.addEventListener('pointerup', released, true)
  window.addEventListener('pointercancel', released, true)
}
