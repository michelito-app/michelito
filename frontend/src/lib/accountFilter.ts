// Cuentas elegidas para el Resumen y Transacciones (lógica pura). La selección vive en la URL
// (`cuentas=k1,k2`) y se recuerda en el navegador; la URL gana cuando está. `null` = todas.
import type { Account } from './api'
import { shortAccountLabel } from './accounts'

export const ACCOUNTS_PARAM = 'cuentas'
/** Parámetro de antes en Transacciones: una sola cuenta. Se sigue leyendo. */
export const LEGACY_ACCOUNT_PARAM = 'cuenta'
export const STORAGE_KEY = 'finanzas.cuentas'

const CREDIT_CARD = 'credit_card'
const BANK_KINDS = new Set(['savings', 'checking'])

export type AccountRef = Pick<Account, 'key' | 'kind' | 'label'>
/** Claves elegidas, ordenadas; `null` = todas las cuentas. */
export type Selection = readonly string[] | null

export type Shortcut = 'all' | 'cards' | 'banks'

export const SHORTCUTS: readonly { shortcut: Shortcut; label: string }[] = [
  { shortcut: 'all', label: 'Todas' },
  { shortcut: 'cards', label: 'Solo tarjetas' },
  { shortcut: 'banks', label: 'Solo cuentas bancarias' },
]

/** "k1,k2" → ["k1", "k2"], sin vacíos ni repetidos; null si no queda nada. */
export function parseKeys(text: string | null | undefined): string[] | null {
  const keys = [...new Set((text ?? '').split(',').map((k) => k.trim()).filter(Boolean))]
  return keys.length ? keys.sort() : null
}

/** Lo elegido en la URL: `cuentas` o, si no está, la `cuenta` de antes. */
export function selectionFromParams(params: URLSearchParams): string[] | null {
  return parseKeys(params.get(ACCOUNTS_PARAM)) ?? parseKeys(params.get(LEGACY_ACCOUNT_PARAM))
}

/** Normaliza una selección: solo claves conocidas (si ya cargaron las cuentas); null si no
 * queda ninguna o están todas. */
export function normalize(keys: readonly string[] | null, accounts?: readonly AccountRef[]): Selection {
  if (keys === null) return null
  const known = accounts && accounts.length ? new Set(accounts.map((a) => a.key)) : null
  const kept = [...new Set(keys)].filter((k) => known === null || known.has(k)).sort()
  if (kept.length === 0) return null
  if (known !== null && kept.length === known.size) return null
  return kept
}

/** La selección vigente: la de la URL si trae una; si no, la recordada. */
export function resolveSelection(
  fromUrl: readonly string[] | null,
  stored: string | null,
  accounts?: readonly AccountRef[],
): Selection {
  return normalize(fromUrl ?? parseKeys(stored), accounts)
}

/** Qué recordar cuando la URL trae una selección: la de la URL (normalizada) si difiere de
 * la recordada; `undefined` si no hay nada que escribir (sin URL, sin cuentas cargadas o
 * igual a lo recordado). Así el menú lleva a las otras pantallas con la misma selección. */
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

/** Texto del parámetro `cuentas`; null para todas. */
export function selectionParam(selection: Selection): string | null {
  return selection === null ? null : selection.join(',')
}

/** Claves de un atajo; `null` (todas) si el atajo no deja nada o deja todo. */
export function shortcutSelection(shortcut: Shortcut, accounts: readonly AccountRef[]): Selection {
  if (shortcut === 'all') return null
  const keys = accounts
    .filter((a) => (shortcut === 'cards' ? a.kind === CREDIT_CARD : BANK_KINDS.has(a.kind)))
    .map((a) => a.key)
  return normalize(keys.length ? keys : null, accounts)
}

/** ¿La selección es exactamente la del atajo? */
export function isShortcut(shortcut: Shortcut, selection: Selection, accounts: readonly AccountRef[]): boolean {
  const target = shortcutSelection(shortcut, accounts)
  if (shortcut !== 'all' && target === null) return false
  return selectionParam(target) === selectionParam(selection)
}

/** ¿Hay alguna cuenta de banco o tarjeta para ese atajo? (si no, no se ofrece). */
export function hasShortcut(shortcut: Shortcut, accounts: readonly AccountRef[]): boolean {
  return shortcut === 'all' || shortcutSelection(shortcut, accounts) !== null
}

export function isSelected(key: string, selection: Selection): boolean {
  return selection === null || selection.includes(key)
}

/** Marca o desmarca una cuenta. La última elegida no se puede quitar (siempre queda una). */
export function toggle(key: string, selection: Selection, accounts: readonly AccountRef[]): Selection {
  const current = selection ?? accounts.map((a) => a.key)
  const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key]
  if (next.length === 0) return selection
  return normalize(next, accounts)
}

/** "Cuentas: Todas", "Cuentas: 2 de 5" o el nombre de la única cuenta elegida. */
export function buttonLabel(selection: Selection, accounts: readonly AccountRef[]): string {
  if (selection === null) return 'Cuentas: Todas'
  if (selection.length === 1) {
    const only = accounts.find((a) => a.key === selection[0])
    return only ? shortAccountLabel(only.label) : `Cuentas: 1 de ${accounts.length}`
  }
  return `Cuentas: ${selection.length} de ${accounts.length || selection.length}`
}

/** Frase del alcance: "todas tus cuentas" (o `all`), "VISA ···4242" o "2 de 5 cuentas". */
export function scopeText(
  selection: Selection,
  accounts: readonly AccountRef[],
  all = 'todas tus cuentas',
): string {
  if (selection === null) return all
  if (selection.length === 1) {
    return accounts.find((a) => a.key === selection[0])?.label ?? selection[0]
  }
  return `${selection.length} de ${accounts.length || selection.length} cuentas`
}

/** ¿Entra alguna tarjeta de crédito en la selección? */
export function includesCard(selection: Selection, accounts: readonly AccountRef[]): boolean {
  return accounts.some((a) => a.kind === CREDIT_CARD && isSelected(a.key, selection))
}

/** Pista de la última cuenta elegida, que no se puede quitar. */
export const LAST_ACCOUNT_HINT = 'Siempre queda al menos una cuenta'

/** Ruta de la API con `accounts=` si hay selección. */
export function withAccounts(path: string, selection: Selection): string {
  const param = selectionParam(selection)
  if (param === null) return path
  const glue = path.includes('?') ? '&' : '?'
  return `${path}${glue}${new URLSearchParams({ accounts: param })}`
}

/** Enlace a otra pantalla con los parámetros dados y la selección (para que los totales
 * cuadren con el Resumen). Sin parámetros queda la ruta sola. */
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

/** Enlace a Transacciones con los parámetros dados y la selección. */
export function transactionsHref(params: Record<string, string>, selection: Selection): string {
  return hrefWithSelection('/transacciones', params, selection)
}

/** Lee la selección recordada; sin acceso al almacenamiento, nada. */
export function readStored(storage: Pick<Storage, 'getItem'> | undefined = globalStorage()): string | null {
  try {
    return storage?.getItem(STORAGE_KEY) ?? null
  } catch {
    return null
  }
}

/** Recuerda la selección (o la olvida con "Todas"); si el navegador no deja, sigue sin ella. */
export function writeStored(
  selection: Selection,
  storage: Pick<Storage, 'setItem' | 'removeItem'> | undefined = globalStorage(),
): void {
  try {
    const param = selectionParam(selection)
    if (param === null) storage?.removeItem(STORAGE_KEY)
    else storage?.setItem(STORAGE_KEY, param)
  } catch {
    // Almacenamiento bloqueado (ventana privada, datos borrados): la URL sigue mandando.
  }
}

function globalStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}
