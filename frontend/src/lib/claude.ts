// "Copy for Claude" (pure logic): the fixed instruction (GET /api/dossier/prompt) plus the
// month's dossier (GET /api/dossier, Markdown) go to the clipboard; nothing leaves from here to
// anywhere else. Only the month and the accounts go in the URL; claude.ai is never opened with
// data.
import { LOCALE, t } from '@/i18n'
import { type Selection, selectionParam } from './accountFilter'

export const HELP = t('claude.help')
export const MANUAL_NOTE = t('claude.manualNote')
export const COPY_EVENT = 'copy_for_claude'
export const HASH_HEADER = 'X-Michelito-Fingerprint'
const HASH = /^[0-9a-f]{16}$/

/** The month's dossier and its fingerprint (that of the data it was built from). */
export interface Dossier {
  markdown: string
  fingerprint: string | null
}

/** The header's fingerprint, when it has the expected shape. */
export function hashFrom(headers: Pick<Headers, 'get'>): string | null {
  const value = headers.get(HASH_HEADER)
  return value !== null && HASH.test(value) ? value : null
}

/** What the dialog keeps while the page lives (it closes and reopens without losing what was
 * pasted). `fingerprint`: that of the dossier that was copied. */
export interface ClaudeDraft {
  instruction: string | null
  answer: string
  fingerprint: string | null
}

export const EMPTY_DRAFT: ClaudeDraft = { instruction: null, answer: '', fingerprint: null }

/** "All" or the list of accounts (with their name when known). */
export function accountsText(keys: readonly string[] | null, labels: ReadonlyMap<string, string>): string {
  if (keys === null || keys.length === 0) return t('claude.allAccounts')
  return keys.map((key) => labels.get(key) ?? key).join(', ')
}

/** Path of the month's dossier with the chosen accounts (nothing else in the URL). */
export function dossierPath(month: string, selection: Selection): string {
  const query = new URLSearchParams({ month })
  const keys = selectionParam(selection)
  if (keys !== null) query.set('accounts', keys)
  return `/api/dossier?${query}`
}

/** What is copied: the instruction (as it was left) and, below it, the dossier. */
export function composeForClaude(instruction: string, dossier: string): string {
  const head = instruction.trim()
  return head ? `${head}\n\n---\n\n${dossier.trim()}\n` : `${dossier.trim()}\n`
}

/** Size and word count ("7.5 KB · 1,234 …"), so it shows how much is pasted. */
export function sizeText(text: string): string {
  const bytes = new TextEncoder().encode(text).length
  const size = bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
  const words = text.split(/\s+/).filter(Boolean).length
  return t('claude.size', { size, words: words.toLocaleString(LOCALE) })
}

export interface ClipboardEnv {
  isSecureContext: boolean
  clipboard?: Pick<Clipboard, 'writeText'>
}

/** Copies with `navigator.clipboard`; 'manual' without a secure context or a clipboard, or when
 * the browser refuses (the interface shows the text selected so it can be copied by hand). */
export async function copyText(text: string, env: ClipboardEnv): Promise<'copied' | 'manual'> {
  if (!env.isSecureContext || !env.clipboard) return 'manual'
  try {
    await env.clipboard.writeText(text)
    return 'copied'
  } catch {
    return 'manual'
  }
}

/** The browser environment for `copyText`. */
export function browserClipboard(): ClipboardEnv {
  return {
    isSecureContext: typeof window !== 'undefined' && window.isSecureContext,
    clipboard: typeof navigator !== 'undefined' ? navigator.clipboard : undefined,
  }
}

/** Body of PUT /api/insights/{month} when the answer is pasted: a new analysis of today's data
 * with the same accounts as the copied dossier. */
export interface PastedBody {
  text: string
  fresh: true
  accounts: string[] | null
  fingerprint?: string
}

export function pastedBody(
  text: string,
  accounts: Selection,
  fingerprint: string | null,
): PastedBody {
  const body: PastedBody = { text, fresh: true, accounts: accounts === null ? null : [...accounts] }
  return fingerprint === null ? body : { ...body, fingerprint }
}
