// «Lectura del mes» del Resumen (lógica pura): qué pestañas lleva la tarjeta.

export type ReadingTab = 'analisis' | 'que-paso' | 'que-cambio'

export const READING_LABELS: Record<ReadingTab, string> = {
  analisis: 'Análisis',
  'que-paso': 'Qué pasó',
  'que-cambio': 'Qué cambió',
}

export interface ReadingContent {
  /** Hay un análisis guardado del mes. */
  insight: boolean
  /** El mes es atípico y hay comercios que lo explican. */
  whatHappened: boolean
  /** Alguna categoría se apartó de lo habitual. */
  changes: boolean
}

/** Las pestañas con contenido, en orden fijo; vacía si no hay nada que leer. */
export function readingTabs(content: ReadingContent): ReadingTab[] {
  const tabs: [ReadingTab, boolean][] = [
    ['analisis', content.insight],
    ['que-paso', content.whatHappened],
    ['que-cambio', content.changes],
  ]
  return tabs.filter(([, has]) => has).map(([tab]) => tab)
}

/** La pestaña elegida si sigue disponible; si no, la primera (o null sin pestañas). */
export function activeTab(tabs: readonly ReadingTab[], chosen: ReadingTab | null): ReadingTab | null {
  if (chosen !== null && tabs.includes(chosen)) return chosen
  return tabs[0] ?? null
}

/** Pestaña vecina con las flechas (da la vuelta en los extremos). */
export function neighborTab(tabs: readonly ReadingTab[], current: ReadingTab, step: 1 | -1): ReadingTab {
  const at = tabs.indexOf(current)
  if (at < 0) return tabs[0] ?? current
  return tabs[(at + step + tabs.length) % tabs.length]
}

/** Por qué «Qué cambió» no trae nada este mes; null si hay cambios. */
export function changesNote(changes: number, partial: boolean, comparable: boolean): string | null {
  if (changes > 0) return null
  if (partial) return 'Qué cambió: se compara cuando todas las cuentas cierran el mes.'
  if (!comparable) return 'Qué cambió: hace falta al menos un mes completo anterior para comparar.'
  return 'Qué cambió: todas las categorías están dentro de lo habitual.'
}
