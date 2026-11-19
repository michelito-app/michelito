// Accounts selected for Summary and Transactions (pure logic). The selection lives in the URL
// (`accounts=k1,k2`) and is remembered in the browser; the URL wins when present. `null` = all.
import { t } from '@/i18n'
import { LEGACY_STORAGE_KEY, translateAccountKeys } from '@/legacy'
import type { Account } from './api'
import { shortAccountLabel } from './accounts'

export const ACCOUNTS_PARAM = 'accounts'
/** Older Transactions parameter: a single account. Still read. */
export const LEGACY_ACCOUNT_PARAM = 'account'
export const STORAGE_KEY = 'michelito.accounts'
/** The key this preference was saved under before the rename (in `@/legacy`): only read as a
 * fallback, with its renamed account keys translated, and removed on the next write. */
export { LEGACY_STORAGE_KEY }

const CREDIT_CARD = 'credit_card'
const BANK_KINDS = new Set(['savings', 'checking'])

export type AccountRef = Pick<Account, 'key' | 'kind' | 'label'>
/** Selected keys, sorted; `null` = all accounts. */
export type Selection = readonly string[] | null

export type Shortcut = 'all' | 'cards' | 'banks'

export const SHORTCUTS: readonly { shortcut: Shortcut; label: string }[] = [
  { shortcut: 'all', label: t('shell.accounts.all') },
  { shortcut: 'cards', label: t('shell.accounts.cardsOnly') },
  { shortcut: 'banks', label: t('shell.accounts.banksOnly') },
]

/** "k1,k2" → ["k1", "k2"], without empties or repeats; null if nothing is left. */
export function parseKeys(text: string | null | undefined): string[] | null {
  const keys = [...new Set((text ?? '').split(',').map((k) => k.trim()).filter(Boolean))]
  return keys.length ? keys.sort() : null
}

/** The selection in the URL: `accounts` or, if missing, the older `account`. */
export function selectionFromParams(params: URLSearchParams): string[] | null {
  return parseKeys(params.get(ACCOUNTS_PARAM)) ?? parseKeys(params.get(LEGACY_ACCOUNT_PARAM))
}

/** Normalizes a selection: only known keys (if the accounts already loaded); null if none is
 * left or all of them are there. */
export function normalize(keys: readonly string[] | null, accounts?: readonly AccountRef[]): Selection {
  if (keys === null) return null
  const known = accounts && accounts.length ? new Set(accounts.map((a) => a.key)) : null
  const kept = [...new Set(keys)].filter((k) => known === null || known.has(k)).sort()
  if (kept.length === 0) return null
  if (known !== null && kept.length === known.size) return null
  return kept
}

/** The current selection: the URL's if it has one; otherwise the remembered one. */
export function resolveSelection(
  fromUrl: readonly string[] | null,
  stored: string | null,
  accounts?: readonly AccountRef[],
): Selection {
  return normalize(fromUrl ?? parseKeys(stored), accounts)
}

/** What to remember when the URL brings a selection: the URL's (normalized) if it differs from
 * the remembered one; `undefined` if there is nothing to write (no URL, accounts not loaded or
 * same as remembered). This way the menu takes the same selection to the other screens. */
export function storedUpdate(
  fromUrl: readonly string[] | null,
  stored: string | null,
  accounts: readonly AccountRef[] | undefined,
): Selection | undefined {
  if (fromUrl === null || !accounts || accounts.length === 0) return undefined
  const wanted = normalize(fromUrl, accounts)
  const current = normalize(parseKeys(stored), accounts)
  return selectionParam(wanted) === selectionParam(current) ? undefined : wanted
}

/** Text of the `accounts` parameter; null for all. */
export function selectionParam(selection: Selection): string | null {
  return selection === null ? null : selection.join(',')
}

/** Keys of a shortcut; `null` (all) if the shortcut leaves nothing or everything. */
export function shortcutSelection(shortcut: Shortcut, accounts: readonly AccountRef[]): Selection {
  if (shortcut === 'all') return null
  const keys = accounts
    .filter((a) => (shortcut === 'cards' ? a.kind === CREDIT_CARD : BANK_KINDS.has(a.kind)))
    .map((a) => a.key)
  return normalize(keys.length ? keys : null, accounts)
}

/** Is the selection exactly the shortcut's? */
export function isShortcut(shortcut: Shortcut, selection: Selection, accounts: readonly AccountRef[]): boolean {
  const target = shortcutSelection(shortcut, accounts)
  if (shortcut !== 'all' && target === null) return false
  return selectionParam(target) === selectionParam(selection)
}

/** Is there any bank account or card for that shortcut? (if not, it is not offered). */
export function hasShortcut(shortcut: Shortcut, accounts: readonly AccountRef[]): boolean {
  return shortcut === 'all' || shortcutSelection(shortcut, accounts) !== null
}

export function isSelected(key: string, selection: Selection): boolean {
  return selection === null || selection.includes(key)
}

/** Checks or unchecks an account. The last selected one cannot be removed (one always stays). */
export function toggle(key: string, selection: Selection, accounts: readonly AccountRef[]): Selection {
  const current = selection ?? accounts.map((a) => a.key)
  const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key]
  if (next.length === 0) return selection
  return normalize(next, accounts)
}

/** "All", "n of m" or the short name of the only selected account. */
export function buttonLabel(selection: Selection, accounts: readonly AccountRef[]): string {
  if (selection === null) return t('shell.accounts.buttonAll')
  if (selection.length === 1) {
    const only = accounts.find((a) => a.key === selection[0])
    return only
      ? shortAccountLabel(only.label)
      : t('shell.accounts.buttonSome', { count: 1, total: accounts.length })
  }
  return t('shell.accounts.buttonSome', {
    count: selection.length,
    total: accounts.length || selection.length,
  })
}

/** Scope phrase: all your accounts (or `all`), the single account ("VISA ···4242") or "n of m". */
export function scopeText(
  selection: Selection,
  accounts: readonly AccountRef[],
  all: string = t('common.allYourAccounts'),
): string {
  if (selection === null) return all
  if (selection.length === 1) {
    return accounts.find((a) => a.key === selection[0])?.label ?? selection[0]
  }
  return t('shell.accounts.scopeSome', {
    count: selection.length,
    total: accounts.length || selection.length,
  })
}

/** Does the selection include any credit card? */
export function includesCard(selection: Selection, accounts: readonly AccountRef[]): boolean {
  return accounts.some((a) => a.kind === CREDIT_CARD && isSelected(a.key, selection))
}

/** Hint for the last selected account, which cannot be removed. */
export const LAST_ACCOUNT_HINT = t('shell.accounts.lastHint')

/** API path with `accounts=` if there is a selection. */
export function withAccounts(path: string, selection: Selection): string {
  const param = selectionParam(selection)
  if (param === null) return path
  const glue = path.includes('?') ? '&' : '?'
  return `${path}${glue}${new URLSearchParams({ accounts: param })}`
}

/** Link to another screen with the given parameters and the selection (so totals match the
 * Summary). Without parameters it is just the path. */
export function hrefWithSelection(
  path: string,
  params: Record<string, string>,
  selection: Selection,
): string {
  const query = new URLSearchParams(params)
  const param = selectionParam(selection)
  if (param !== null) query.set(ACCOUNTS_PARAM, param)
  const text = query.toString()
  return text ? `${path}?${text}` : path
}

/** Link to Transactions with the given parameters and the selection. */
export function transactionsHref(params: Record<string, string>, selection: Selection): string {
  return hrefWithSelection('/transactions', params, selection)
}

/** Reads the remembered selection; without storage access, nothing. */
export function readStored(storage: Pick<Storage, 'getItem'> | undefined = globalStorage()): string | null {
  try {
    const current = storage?.getItem(STORAGE_KEY)
    if (current != null) return current
    const old = storage?.getItem(LEGACY_STORAGE_KEY)
    return old == null ? null : translateAccountKeys(old)
  } catch {
    return null
  }
}

/** Remembers the selection (or forgets it with "All"); if the browser refuses, goes on without. */
export function writeStored(
  selection: Selection,
  storage: Pick<Storage, 'setItem' | 'removeItem'> | undefined = globalStorage(),
): void {
  try {
    const param = selectionParam(selection)
    storage?.removeItem(LEGACY_STORAGE_KEY)
    if (param === null) storage?.removeItem(STORAGE_KEY)
    else storage?.setItem(STORAGE_KEY, param)
  } catch {
    // Storage blocked (private window, cleared data): the URL still rules.
  }
}

function globalStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}
