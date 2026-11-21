// Queries of the Summary's cards that no other screen uses.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { type Selection, selectionParam, withAccounts } from './accountFilter'
import { request } from './api'
import { DISMISSED_KEY, type Invitation, parseDismissed } from './home'

/** GET /api/summary/pace: cumulative spending per day against last month, up to today. */
export interface Pace {
  month: string
  previous_month: string
  through_day: number
  days_in_month: number
  current_cents: number[]
  previous_cents: number[]
  total_to_date_cents: number
  previous_same_day_cents: number
  previous_same_day_total_cents: number
  finished: boolean // the month is over: compared with the whole of last month
  one_offs: { fingerprint: string; day: string; merchant: string; amount_cents: number }[]
  today: string // the server's today
}

/** Under the Summary's key: whatever invalidates the Summary also refreshes the pace. */
export function usePace(month: string, selection: Selection) {
  return useQuery({
    queryKey: ['summary', 'pace', month, selectionParam(selection) ?? 'all'] as const,
    queryFn: () =>
      request<Pace>(withAccounts(`/api/summary/pace?month=${encodeURIComponent(month)}`, selection)),
    placeholderData: keepPreviousData,
  })
}

function readDismissed(): Invitation[] {
  try {
    return parseDismissed(window.localStorage.getItem(DISMISSED_KEY))
  } catch {
    return []
  }
}

/** The invitations dismissed with «×», remembered in this browser (without storage, for the
 * session only). */
export function useDismissedInvitations(): [readonly Invitation[], (kind: Invitation) => void] {
  const [dismissed, setDismissed] = useState<readonly Invitation[]>(readDismissed)
  function dismiss(kind: Invitation) {
    const next = [...new Set([...readDismissed(), ...dismissed, kind])]
    try {
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next))
    } catch {
      // Storage blocked: it stays dismissed until the page reloads.
    }
    setDismissed(next)
  }
  return [dismissed, dismiss]
}
