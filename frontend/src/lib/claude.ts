// «Copiar para Claude» (lógica pura): la instrucción fija (GET /api/dossier/instruccion) más el
// dossier del mes (GET /api/dossier, Markdown) van al portapapeles; nada sale de aquí a otro
// lado. En la URL solo van el mes y las cuentas; nunca se abre claude.ai con datos.
import { type Selection, selectionParam } from './accountFilter'

export const HELP = 'Pégalo en Claude (claude.ai, la app o Claude Code) y pega aquí la respuesta'
export const MANUAL_NOTE =
  'No se pudo copiar solo: el texto quedó seleccionado abajo; cópialo con Ctrl+C (o mantén pulsado y «Copiar»).'
export const COPY_EVENT = 'copiar_claude'
export const HASH_HEADER = 'X-Finanzas-Huella'
const HASH = /^[0-9a-f]{16}$/

/** El dossier del mes y su huella (la de los datos con que se armó). */
export interface Dossier {
  markdown: string
  huella: string | null
}

/** La huella de la cabecera, si tiene la forma esperada. */
export function hashFrom(headers: Pick<Headers, 'get'>): string | null {
  const value = headers.get(HASH_HEADER)
  return value !== null && HASH.test(value) ? value : null
}

/** Lo que se lleva el diálogo mientras la página vive (se cierra y se vuelve a abrir sin perder
 * lo pegado). `huella`: la del dossier que se copió. */
export interface ClaudeDraft {
  instruction: string | null
  answer: string
  huella: string | null
}

export const EMPTY_DRAFT: ClaudeDraft = { instruction: null, answer: '', huella: null }

/** «todas las cuentas» o la lista de cuentas (con su nombre si se conoce). */
export function accountsText(keys: readonly string[] | null, labels: ReadonlyMap<string, string>): string {
  if (keys === null || keys.length === 0) return 'todas'
  return keys.map((key) => labels.get(key) ?? key).join(', ')
}

/** Ruta del dossier del mes con las cuentas elegidas (nada más en la URL). */
export function dossierPath(month: string, selection: Selection): string {
  const query = new URLSearchParams({ mes: month })
  const keys = selectionParam(selection)
  if (keys !== null) query.set('cuentas', keys)
  return `/api/dossier?${query}`
}

/** Lo que se copia: la instrucción (tal como quedó) y, debajo, el dossier. */
export function composeForClaude(instruction: string, dossier: string): string {
  const head = instruction.trim()
  return head ? `${head}\n\n---\n\n${dossier.trim()}\n` : `${dossier.trim()}\n`
}

/** «7.5 KB · 1,234 palabras» (para que se vea cuánto se pega). */
export function sizeText(text: string): string {
  const bytes = new TextEncoder().encode(text).length
  const size = bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
  const words = text.split(/\s+/).filter(Boolean).length
  return `${size} · ${words.toLocaleString('en-US')} palabras`
}

export interface ClipboardEnv {
  isSecureContext: boolean
  clipboard?: Pick<Clipboard, 'writeText'>
}

/** Copia con `navigator.clipboard`; 'manual' si no hay contexto seguro, no hay portapapeles o
 * el navegador lo niega (la interfaz muestra el texto seleccionado para copiarlo a mano). */
export async function copyText(text: string, env: ClipboardEnv): Promise<'copiado' | 'manual'> {
  if (!env.isSecureContext || !env.clipboard) return 'manual'
  try {
    await env.clipboard.writeText(text)
    return 'copiado'
  } catch {
    return 'manual'
  }
}

/** El entorno del navegador para `copyText`. */
export function browserClipboard(): ClipboardEnv {
  return {
    isSecureContext: typeof window !== 'undefined' && window.isSecureContext,
    clipboard: typeof navigator !== 'undefined' ? navigator.clipboard : undefined,
  }
}

/** Cuerpo de PUT /api/insights/{mes} al pegar la respuesta: un análisis nuevo de los datos de
 * hoy con las mismas cuentas del dossier copiado. */
export interface PastedBody {
  text: string
  fresh: true
  accounts: string[] | null
  huella?: string
}

export function pastedBody(text: string, accounts: Selection, huella: string | null): PastedBody {
  const body: PastedBody = { text, fresh: true, accounts: accounts === null ? null : [...accounts] }
  return huella === null ? body : { ...body, huella }
}
