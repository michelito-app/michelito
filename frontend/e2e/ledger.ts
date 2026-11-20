// Helpers for the specs that write to Shared (the ledger). The e2e server keeps one database for
// every spec and project (they run one after another), so a spec that writes undoes all of it at
// the end through the change log, newest first, and the next one finds the made-up data intact.
import { expect, type APIRequestContext } from '@playwright/test'
import type { Contacts, Group, NewPerson } from '../src/lib/sharedApi'

const HEADERS = { 'X-Michelito': '1' }

/** What the log API says of an entry (src/lib/log.ts), as much as the cleanup needs. */
interface LogEntry {
  id: number
  undoes: number | null
  undone: boolean
}

interface LogPage {
  items: LogEntry[]
}

/** The newest log entry's id: everything after it belongs to the test. */
export async function logMark(request: APIRequestContext): Promise<number> {
  const response = await request.get('/api/log?limit=1')
  const page = (await response.json()) as LogPage
  return page.items[0]?.id ?? 0
}

/** Undoes every change after `mark` (the ones already undone, and the undo entries themselves,
 * are skipped). A change blocked by a newer one is retried once the newer one is undone. */
export async function undoSince(request: APIRequestContext, mark: number): Promise<void> {
  for (let pass = 0; pass < 6; pass++) {
    const response = await request.get('/api/log?limit=200')
    const items = ((await response.json()) as LogPage).items
    const left = items.filter((e: LogEntry) => e.id > mark && e.undoes === null && !e.undone)
    if (left.length === 0) return
    for (const entry of left) {
      await request.post(`/api/log/${entry.id}/undo`, { headers: HEADERS })
    }
  }
  throw new Error(`could not undo every change after log entry ${mark}`)
}

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  expect(response.ok(), await response.text()).toBe(true)
  return (await response.json()) as T
}

export async function contacts(request: APIRequestContext): Promise<Contacts> {
  return json<Contacts>(await request.get('/api/shared/contacts'))
}

export async function createGroup(
  request: APIRequestContext,
  name: string,
  people: NewPerson[],
): Promise<Group> {
  return json<Group>(
    await request.post('/api/shared/groups', { headers: HEADERS, data: { name, people } }),
  )
}

export async function addEntry(
  request: APIRequestContext,
  groupId: number,
  body: Record<string, unknown>,
): Promise<Group> {
  return json<Group>(
    await request.post(`/api/shared/groups/${groupId}/entries`, { headers: HEADERS, data: body }),
  )
}

export async function addPayment(
  request: APIRequestContext,
  groupId: number,
  body: Record<string, unknown>,
): Promise<Group> {
  return json<Group>(
    await request.post(`/api/shared/groups/${groupId}/payments`, { headers: HEADERS, data: body }),
  )
}

/** The fingerprint of a month's transaction by its merchant. */
export async function fingerprintOf(
  request: APIRequestContext,
  month: string,
  merchant: RegExp,
): Promise<string> {
  const data = await json<{ items: { fingerprint: string; merchant: string; description: string }[] }>(
    await request.get(`/api/transactions?month=${month}`),
  )
  const found = data.items.find((tx) => merchant.test(tx.description) || merchant.test(tx.merchant))
  expect(found, String(merchant)).toBeTruthy()
  return found!.fingerprint
}
