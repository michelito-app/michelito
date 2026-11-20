// The server's mode (GET /api/mode) and the public demo's parts: session, feedback, usage and the
// sample statement (src/michelito/demo/routes.py). The pure logic is kept apart from the calls.
import { createContext, useContext } from 'react'
import { LOCALE, t } from '@/i18n'
import { ApiError, request } from '@/lib/api'

export interface ModeInfo {
  mode: 'local' | 'demo' | 'hosted'
  session: boolean
  name?: string
  version?: string
  repo?: string
  notice?: string
  demo_url?: string // hosted: the public demo, linked from the signed-out page
  return_url?: string // demo: the hosted app, for the "sample data" band's way back
}

export const LOCAL: ModeInfo = { mode: 'local', session: true }
export const LOCAL_NAME = 'Michelito'
export const OPINION_MAX = 2000
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const REF = /^[A-Za-z0-9_.-]{1,64}$/

export const ModeContext = createContext<ModeInfo>(LOCAL)

export function useMode(): ModeInfo {
  return useContext(ModeContext)
}

export function isDemo(mode: ModeInfo): boolean {
  return mode.mode === 'demo'
}

export function isHosted(mode: ModeInfo): boolean {
  return mode.mode === 'hosted'
}

/** Visible name: the demo's name, or the usual one when local. */
export function productName(mode: ModeInfo): string {
  return isDemo(mode) && mode.name ? mode.name : LOCAL_NAME
}

/** The entry URL's `?ref=`, when it has an acceptable shape (otherwise it is ignored). */
export function refFrom(search: string): string | null {
  const ref = new URLSearchParams(search).get('ref')?.trim() ?? ''
  return REF.test(ref) ? ref : null
}

/** What keeps the feedback from being sent (null: it can be sent). */
export function opinionProblem(text: string, email: string): string | null {
  const body = text.trim()
  if (!body) return t('demo.opinion.empty')
  if (body.length > OPINION_MAX) {
    return t('demo.opinion.tooLong', { max: OPINION_MAX.toLocaleString(LOCALE) })
  }
  const mail = email.trim()
  if (mail && !EMAIL.test(mail)) return t('demo.opinion.badEmail')
  return null
}

export interface OpinionBody {
  text: string
  email: string | null
  page: string
  width: number
  version: string | null
  ref: string | null
}

/** Body of POST /api/feedback with the context that is sent on its own. */
export function opinionBody(
  text: string,
  email: string,
  context: { path: string; width: number; version?: string; ref: string | null },
): OpinionBody {
  return {
    text: text.trim(),
    email: email.trim() || null,
    page: context.path,
    width: Math.round(context.width),
    version: context.version ?? null,
    ref: context.ref,
  }
}

export interface SampleResult {
  balanced: boolean
  status: string
  detail: string | null
  transactions: number
  account: string
  period_start: string
  period_end: string
  months: string[]
}

/** The server's mode. Only a server without `/api/mode` (404: an old one) counts as local; any
 * other error propagates (the demo must not open half-way). */
export async function fetchMode(): Promise<ModeInfo> {
  try {
    return await request<ModeInfo>('/api/mode')
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return LOCAL
    throw error
  }
}

/** "Start over": a new copy of the template instead of the visitor's. */
export async function restartCopy(): Promise<void> {
  await request('/api/demo/restart', { method: 'POST' })
}

export async function startSession(): Promise<void> {
  await request('/api/demo/session', { method: 'POST' })
}

export async function sendOpinion(body: OpinionBody): Promise<void> {
  await request('/api/feedback', { method: 'POST', body: JSON.stringify(body) })
}

export async function importSample(): Promise<SampleResult> {
  return request<SampleResult>('/api/demo/sample-statement', { method: 'POST' })
}

/** Counts the visit to a screen; an error does not matter (it is only a counter). */
export function countVisit(path: string): void {
  // The SPA routes are the screen keys the backend counts (src/michelito/demo/feedback_store.py).
  const body = JSON.stringify({ screen: path })
  request('/api/usage', { method: 'POST', body }).catch(() => undefined)
}

/** Counts an interface event (e.g. "copy for Claude"); an error does not matter. */
export function countEvent(name: string): void {
  request('/api/demo/event', { method: 'POST', body: JSON.stringify({ event: name }) }).catch(
    () => undefined,
  )
}
