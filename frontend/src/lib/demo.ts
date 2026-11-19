// Modo del servidor (GET /api/modo) y lo de la demo pública: sesión, opiniones, uso y el estado
// de ejemplo (src/finanzas/demo/rutas.py). La lógica pura va aparte de las llamadas.
import { createContext, useContext } from 'react'
import { ApiError, request } from '@/lib/api'

export interface ModeInfo {
  modo: 'local' | 'demo'
  sesion: boolean
  nombre?: string
  version?: string
  repo?: string
  aviso?: string
}

export const LOCAL: ModeInfo = { modo: 'local', sesion: true }
export const LOCAL_NAME = 'Finanzas'
export const OPINION_MAX = 2000
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const REF = /^[A-Za-z0-9_.-]{1,64}$/

export const ModeContext = createContext<ModeInfo>(LOCAL)

export function useMode(): ModeInfo {
  return useContext(ModeContext)
}

export function isDemo(mode: ModeInfo): boolean {
  return mode.modo === 'demo'
}

/** Nombre visible: el de la demo («Michelito») o el de siempre en local. */
export function productName(mode: ModeInfo): string {
  return isDemo(mode) && mode.nombre ? mode.nombre : LOCAL_NAME
}

/** `?ref=` de la URL de entrada, si tiene una forma aceptable (si no, se ignora). */
export function refFrom(search: string): string | null {
  const ref = new URLSearchParams(search).get('ref')?.trim() ?? ''
  return REF.test(ref) ? ref : null
}

/** Qué impide enviar la opinión (null: se puede). */
export function opinionProblem(text: string, email: string): string | null {
  const body = text.trim()
  if (!body) return 'Escribe tu opinión.'
  if (body.length > OPINION_MAX) return `Máximo ${OPINION_MAX.toLocaleString('en-US')} letras.`
  const mail = email.trim()
  if (mail && !EMAIL.test(mail)) return 'El correo no parece válido.'
  return null
}

export interface OpinionBody {
  texto: string
  correo: string | null
  pagina: string
  ancho: number
  version: string | null
  ref: string | null
}

/** Cuerpo de POST /api/opiniones con el contexto que se manda solo. */
export function opinionBody(
  text: string,
  email: string,
  context: { path: string; width: number; version?: string; ref: string | null },
): OpinionBody {
  return {
    texto: text.trim(),
    correo: email.trim() || null,
    pagina: context.path,
    ancho: Math.round(context.width),
    version: context.version ?? null,
    ref: context.ref,
  }
}

export interface SampleResult {
  cuadra: boolean
  estado: string
  detalle: string | null
  transacciones: number
  cuenta: string
  desde: string
  hasta: string
  meses: string[]
}

/** El modo del servidor. Solo un servidor sin `/api/modo` (404: uno viejo) cuenta como local;
 * cualquier otro error se propaga (la demo no debe abrirse a medias). */
export async function fetchMode(): Promise<ModeInfo> {
  try {
    return await request<ModeInfo>('/api/modo')
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return LOCAL
    throw error
  }
}

/** «Empezar de nuevo»: una copia nueva de la plantilla en lugar de la del visitante. */
export async function restartCopy(): Promise<void> {
  await request('/api/demo/reiniciar', { method: 'POST' })
}

export async function startSession(): Promise<void> {
  await request('/api/demo/sesion', { method: 'POST' })
}

export async function sendOpinion(body: OpinionBody): Promise<void> {
  await request('/api/opiniones', { method: 'POST', body: JSON.stringify(body) })
}

export async function importSample(): Promise<SampleResult> {
  return request<SampleResult>('/api/demo/estado-ejemplo', { method: 'POST' })
}

/** Cuenta la visita a una pantalla; un error no importa (es solo un contador). */
export function countVisit(path: string): void {
  request('/api/uso', { method: 'POST', body: JSON.stringify({ pantalla: path }) }).catch(
    () => undefined,
  )
}

/** Cuenta un evento de la interfaz (p. ej. «copiar para Claude»); un error no importa. */
export function countEvent(name: string): void {
  request('/api/demo/evento', { method: 'POST', body: JSON.stringify({ evento: name }) }).catch(
    () => undefined,
  )
}
