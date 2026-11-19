// Which collapsible sections of the phone's Summary are open: a visual preference only, kept in
// this browser (closed by default; without storage everything stays closed).
import { useState } from 'react'

export const SECTIONS_KEY = 'michelito.summary.openSections'

/** The stored ids, ignoring anything that is not a list of strings. */
export function parseOpen(raw: string | null): string[] {
  if (raw === null) return []
  try {
    const value: unknown = JSON.parse(raw)
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

/** `open` with `id` added or removed. */
export function withSection(open: readonly string[], id: string, isOpen: boolean): string[] {
  const rest = open.filter((v) => v !== id)
  return isOpen ? [...rest, id] : rest
}

function read(): string[] {
  try {
    return parseOpen(window.localStorage.getItem(SECTIONS_KEY))
  } catch {
    return []
  }
}

function write(open: readonly string[]): void {
  try {
    window.localStorage.setItem(SECTIONS_KEY, JSON.stringify(open))
  } catch {
    // Without storage (private mode, blocked) the preference simply is not remembered.
  }
}

export function useOpenSections(): [readonly string[], (id: string, isOpen: boolean) => void] {
  const [open, setOpen] = useState<readonly string[]>(read)
  function set(id: string, isOpen: boolean) {
    const next = withSection(read(), id, isOpen)
    write(next)
    setOpen(next)
  }
  return [open, set]
}
