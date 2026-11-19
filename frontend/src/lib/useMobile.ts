// Phone layout (below Tailwind's `md`, 768 px): bottom bar, full-screen transaction detail and
// bottom sheets. Wider screens keep the desktop layout.
import { useSyncExternalStore } from 'react'

export const MOBILE_QUERY = '(max-width: 767.98px)'

function subscribe(onChange: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const query = window.matchMedia(MOBILE_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

function snapshot(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.(MOBILE_QUERY).matches
}

/** Is the window phone-sized? Follows resizes and rotations. */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}
