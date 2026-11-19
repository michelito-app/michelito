// Identifiers from before the English rename, isolated on purpose (the frontend counterpart of
// src/michelito/legacy.py). They are only read, so links, bookmarks and browser storage saved by
// the Spanish release keep working; nothing here is ever written. scripts/check_spanish.py allows
// Spanish in this file only.

/** localStorage key under which the account selection was saved before the rename. */
export const LEGACY_STORAGE_KEY = 'finanzas.cuentas'

/** Account keys and fingerprint prefixes that the schema 18 migration renamed in the database. */
const ACCOUNT_KEYS: Readonly<Record<string, string>> = { 'manual:caja-fuerte': 'manual:cash-box' }
const CASH_FINGERPRINT = /^caja-(\d+)$/

/** A comma-separated list of account keys with the renamed ones translated. */
export function translateAccountKeys(text: string): string {
  return text
    .split(',')
    .map((key) => ACCOUNT_KEYS[key.trim()] ?? key)
    .join(',')
}

/** A fingerprint with the old cash box prefix translated (`caja-7` → `cash-7`). */
export function translateFingerprint(fingerprint: string): string {
  const cash = CASH_FINGERPRINT.exec(fingerprint)
  return cash ? `cash-${cash[1]}` : fingerprint
}

/** Old SPA paths (first segment) → new ones. */
const PATHS: Readonly<Record<string, string>> = {
  transacciones: 'transactions',
  presupuesto: 'budget',
  pendientes: 'pending',
  compartidos: 'shared',
  inversiones: 'investments',
  recurrentes: 'recurring',
  reportes: 'reports',
  cuentas: 'accounts',
  categorias: 'categories',
  bitacora: 'log',
  importar: 'import',
}

/** Old query parameters → new ones. */
const PARAMS: Readonly<Record<string, string>> = {
  mes: 'month',
  cuentas: 'accounts',
  cuenta: 'account',
  categoria: 'category',
  tipo: 'kind',
  agrupar: 'group',
  grupo: 'group',
  orden: 'sort',
  compartidos: 'shared',
  estado: 'status',
  inversion: 'investment',
  desde: 'from',
  hasta: 'to',
  pendientes: 'pending',
}

/** Old values of some parameters (by new parameter name) → new ones. */
const VALUES: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  kind: { gastos: 'expense', ingresos: 'income', transferencias: 'transfer' },
  group: { categoria: 'category', comercio: 'merchant' },
  sort: { monto: 'amount' },
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

function translateParams(search: string): string {
  const out = new URLSearchParams()
  for (const [name, value] of new URLSearchParams(search)) {
    const key = PARAMS[name] ?? name
    let translated = VALUES[key]?.[value] ?? value
    if (key === 'accounts' || key === 'account') translated = translateAccountKeys(translated)
    if (key === 'tx') translated = translateFingerprint(translated)
    out.append(key, translated)
  }
  const text = out.toString()
  return text ? `?${text}` : ''
}

/** Where an old Spanish path should go (with its query string translated), or null if `pathname`
 * is not an old path. */
export function legacyRedirect(pathname: string, search: string): string | null {
  const [first, ...rest] = pathname.split('/').filter(Boolean)
  const target = first === undefined ? undefined : PATHS[first]
  if (target === undefined) return null
  // `/transacciones/:huella` → `/transactions/:fingerprint`; other old paths had no sub-path.
  if (rest.length > 0 && target !== 'transactions') return null
  const tail = rest.map((segment) => translateFingerprint(safeDecode(segment)))
  const path = ['', target, ...tail.map(encodeURIComponent)].join('/')
  return `${path}${translateParams(search)}`
}
