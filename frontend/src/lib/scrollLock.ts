// While a sheet or the phone's full-screen detail covers the page, the page itself does not
// scroll (dragging the backdrop would move it). Locks nest: the page's own value comes back when
// the last one is released.
let locks = 0
let saved = ''

/** Locks the page's scroll; call the returned function (once) to release it. */
export function lockScroll(root: HTMLElement = document.documentElement): () => void {
  if (locks === 0) {
    saved = root.style.overflow
    root.style.overflow = 'hidden'
  }
  locks++
  let released = false
  return () => {
    if (released) return
    released = true
    locks--
    if (locks === 0) root.style.overflow = saved
  }
}
