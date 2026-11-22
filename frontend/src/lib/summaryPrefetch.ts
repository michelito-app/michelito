// What the Summary fetches ahead of the cards that show it: this month's pace next to the
// summary (the card that asks for it only mounts once the summary is in), and the months around
// once this one is in, so changing the month finds its answer waiting.
import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { type Selection, selectionParam } from './accountFilter'
import { paceOptions } from './homeQueries'
import type { Neighbors } from './months'
import { summaryOptions } from './queries'

/** One answer to fetch ahead: its key (what the screen will ask for) and how to fetch it. */
export interface Prefetch {
  queryKey: readonly unknown[]
  run: (client: QueryClient) => Promise<void>
}

/** `missing`: only when nothing is there yet. A month around needs an answer to show at once;
 * the screen refreshes it when the person goes there, so fetching it again here is wasted. */
function summaryAhead(month: string, selection: Selection, missing: boolean): Prefetch {
  const options = summaryOptions(month, selection)
  return {
    queryKey: options.queryKey,
    run: async (client) => {
      if (missing && client.getQueryData(options.queryKey) !== undefined) return
      await client.prefetchQuery(options)
    },
  }
}

function paceAhead(month: string, selection: Selection, missing: boolean): Prefetch {
  const options = paceOptions(month, selection)
  return {
    queryKey: options.queryKey,
    run: async (client) => {
      if (missing && client.getQueryData(options.queryKey) !== undefined) return
      await client.prefetchQuery(options)
    },
  }
}

/** In order: this month's pace; then, once `loaded` (this month's summary is in), the summary
 * and the pace of the older and the newer month. Nothing without a month. */
export function summaryPrefetches(
  month: string | null,
  around: Neighbors,
  selection: Selection,
  loaded: boolean,
): Prefetch[] {
  if (month === null) return []
  const sides = loaded ? [around.older, around.newer].filter((side) => side !== null) : []
  return [
    paceAhead(month, selection, false),
    ...sides.flatMap((side) => [
      summaryAhead(side, selection, true),
      paceAhead(side, selection, true),
    ]),
  ]
}

/** Fetches them one after another (the server works on one at a time anyway; this leaves room
 * for what the screen itself asks), stopping when `signal` aborts. A failure stays quiet: the
 * screen that needs the answer asks again and shows the error. */
export async function prefetchSummary(
  client: QueryClient,
  wanted: readonly Prefetch[],
  signal?: AbortSignal,
): Promise<void> {
  for (const ahead of wanted) {
    if (signal?.aborted) return
    await ahead.run(client)
  }
}

/** Keeps the Summary's month and the months around it fetched (see `summaryPrefetches`). */
export function useSummaryPrefetch(
  month: string | null,
  around: Neighbors,
  selection: Selection,
  loaded: boolean,
): void {
  const client = useQueryClient()
  const accounts = selectionParam(selection)
  const { older, newer } = around
  useEffect(() => {
    const controller = new AbortController()
    const chosen = accounts === null ? null : accounts.split(',')
    void prefetchSummary(
      client,
      summaryPrefetches(month, { older, newer }, chosen, loaded),
      controller.signal,
    )
    return () => controller.abort()
  }, [client, month, older, newer, accounts, loaded])
}
