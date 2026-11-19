// Análisis del mes guardados (lógica pura). Los escribe Claude Code a partir de
// `finanzas analisis AAAA-MM` y se guardan con `finanzas insight guardar` (ver README).
import type { Insight, MonthOption } from './api'
import { longDay } from './months'

export const TEXT_MAX = 4000

/** El comando que imprime el dossier del mes para analizarlo. */
export function analyzeCommand(month: string): string {
  return `finanzas analisis ${month}`
}

/** Meses con datos que aún no tienen análisis, del más reciente al más viejo. */
export function monthsWithout(insights: readonly Insight[], months: readonly MonthOption[]): MonthOption[] {
  const done = new Set(insights.map((i) => i.month))
  return months.filter((m) => !done.has(m.month))
}

/** "Guardado el 5 de marzo de 2026" (o "Editado el …" si cambió después). */
export function savedText(insight: Insight): string {
  const edited = insight.updated_at.slice(0, 10) !== insight.created_at.slice(0, 10)
  const day = insight.updated_at.slice(0, 10)
  return `${edited ? 'Editado' : 'Guardado'} el ${longDay(day)} de ${day.slice(0, 4)}`
}

export const STALE_NOTE = 'Los datos cambiaron desde este análisis'

/** Caracteres que quedan; negativo si se pasa. */
export function remaining(text: string): number {
  return TEXT_MAX - text.trim().length
}

/** ¿Se puede guardar este texto? (no vacío y hasta TEXT_MAX). */
export function canSave(text: string): boolean {
  const left = remaining(text)
  return text.trim().length > 0 && left >= 0
}

export type Block =
  | { kind: 'heading'; text: string }
  | { kind: 'list'; items: string[] }
  | { kind: 'paragraph'; text: string }

const HEADING = /^#{1,6}\s+(.*)$/
const ITEM = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/

/** Quita el marcado en línea que no se muestra (**negrita**, `código`, _énfasis_). */
function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1').replace(/\b_(.+?)_\b/g, '$1').trim()
}

/** Markdown sencillo (títulos, listas y párrafos) en bloques de texto plano: se muestra sin
 * insertar HTML. Lo demás queda como texto. */
export function markdownBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', text: plain(paragraph.join(' ')) })
    paragraph = []
  }
  for (const line of text.split('\n')) {
    const heading = HEADING.exec(line)
    const item = ITEM.exec(line)
    if (line.trim() === '') {
      flush()
    } else if (heading) {
      flush()
      blocks.push({ kind: 'heading', text: plain(heading[1]) })
    } else if (item) {
      flush()
      const last = blocks[blocks.length - 1]
      if (last?.kind === 'list') last.items.push(plain(item[1]))
      else blocks.push({ kind: 'list', items: [plain(item[1])] })
    } else {
      paragraph.push(line.trim())
    }
  }
  flush()
  return blocks
}

/** Ruta de la API del análisis de un mes. */
export function insightPath(month: string): string {
  return `/api/insights/${encodeURIComponent(month)}`
}
