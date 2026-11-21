// Scroll position of a screen per history entry: going back to it (system «Back» or the app's)
// returns to where it was, even when its content loads in pieces after it mounts. Moving to a
// new screen starts at the top.
import { useEffect, useLayoutEffect, useRef } from 'react'
import { useLocation, useNavigationType } from 'react-router'

const PREFIX = 'michelito.scroll.'
const INDEX_KEY = 'michelito.scroll.keys'
/** History entries remembered at most (the oldest are forgotten). */
export const MAX_ENTRIES = 30
/** The key of an entry the router did not create (a fresh load or a typed address): it is shared
 * by unrelated visits, so nothing is restored for it. */
export const DEFAULT_KEY = 'default'
/** How long to keep restoring while the content grows (cards loading one by one). */
const RESTORE_MS = 3000

/** The stored position, or null when there is none (or it is unreadable). */
export function parsePosition(raw: string | null): number | null {
  if (raw === null) return null
  const value = Number(raw)
  return Number.isFinite(value) && value >= 0 ? value : null
}

/** The remembered keys after writing `key` (most recent last) and the ones to forget. */
export function withKey(
  keys: readonly string[],
  key: string,
  max = MAX_ENTRIES,
): { keys: string[]; dropped: string[] } {
  const next = [...keys.filter((k) => k !== key), key]
  const cut = Math.max(0, next.length - max)
  return { keys: next.slice(cut), dropped: next.slice(0, cut) }
}

/** The stored list of keys, ignoring anything that is not a list of strings. */
export function parseKeys(raw: string | null): string[] {
  if (raw === null) return []
  try {
    const value: unknown = JSON.parse(raw)
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

function read(key: string): number | null {
  if (key === DEFAULT_KEY) return null
  try {
    return parsePosition(window.sessionStorage.getItem(PREFIX + key))
  } catch {
    return null
  }
}

function write(key: string, y: number): void {
  if (key === DEFAULT_KEY) return
  try {
    const storage = window.sessionStorage
    const { keys, dropped } = withKey(parseKeys(storage.getItem(INDEX_KEY)), key)
    for (const old of dropped) storage.removeItem(PREFIX + old)
    storage.setItem(INDEX_KEY, JSON.stringify(keys))
    storage.setItem(PREFIX + key, String(Math.round(y)))
  } catch {
    // Storage blocked: going back starts at the top.
  }
}

/** Remembers this screen's scroll for the current history entry and restores it when the entry
 * is visited again. While the page is shorter than the position (cards still loading), it keeps
 * trying until it gets there, the user scrolls or `RESTORE_MS` pass.
 *
 * The scroll listener goes away in a layout effect: by the time a passive cleanup runs, the next
 * screen is already in the page and its (clamped) scroll would be stored under this entry. */
export function useScrollMemory(): void {
  const { key } = useLocation()

  useLayoutEffect(() => {
    const onScroll = () => write(key, window.scrollY)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [key])

  useEffect(() => {
    const target = read(key)
    if (target === null || target <= 0) return
    let restoring = true
    const stop = () => {
      restoring = false
    }
    const tryRestore = () => {
      if (!restoring) return
      window.scrollTo(0, target)
      if (Math.abs(window.scrollY - target) < 2) restoring = false
    }
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(tryRestore)
    tryRestore()
    observer?.observe(document.body)
    const timer = window.setTimeout(stop, RESTORE_MS)
    window.addEventListener('wheel', stop, { passive: true })
    window.addEventListener('touchstart', stop, { passive: true })
    window.addEventListener('keydown', stop)
    return () => {
      observer?.disconnect()
      window.clearTimeout(timer)
      window.removeEventListener('wheel', stop)
      window.removeEventListener('touchstart', stop)
      window.removeEventListener('keydown', stop)
    }
  }, [key])
}

/** A new screen (a link followed, not «Back») starts at the top. Only when the path changes:
 * opening a row's detail within the same list keeps the list where it was. */
export function useScrollToTopOnNewScreen(): void {
  const { pathname } = useLocation()
  const type = useNavigationType()
  const shown = useRef(pathname)
  // Only a new path counts: a change of query (a filter, the month, a row) keeps the scroll.
  useLayoutEffect(() => {
    if (shown.current === pathname) return
    shown.current = pathname
    if (type === 'PUSH') window.scrollTo(0, 0)
  }, [pathname, type])
}
