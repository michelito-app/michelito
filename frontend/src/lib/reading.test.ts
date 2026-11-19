import { describe, expect, it } from 'vitest'
import { activeTab, changesNote, neighborTab, readingTabs } from './reading'

describe('readingTabs', () => {
  it('solo las pestañas con contenido, en orden fijo', () => {
    expect(readingTabs({ insight: true, whatHappened: true, changes: true })).toEqual([
      'analisis',
      'que-paso',
      'que-cambio',
    ])
    expect(readingTabs({ insight: false, whatHappened: true, changes: true })).toEqual([
      'que-paso',
      'que-cambio',
    ])
    expect(readingTabs({ insight: true, whatHappened: false, changes: false })).toEqual(['analisis'])
  })

  it('sin nada que leer no hay pestañas', () => {
    expect(readingTabs({ insight: false, whatHappened: false, changes: false })).toEqual([])
  })
})

describe('activeTab', () => {
  it('conserva la elegida si sigue; si no, la primera', () => {
    expect(activeTab(['analisis', 'que-cambio'], 'que-cambio')).toBe('que-cambio')
    expect(activeTab(['analisis', 'que-cambio'], 'que-paso')).toBe('analisis')
    expect(activeTab(['que-cambio'], null)).toBe('que-cambio')
    expect(activeTab([], 'analisis')).toBeNull()
  })
})

describe('neighborTab', () => {
  it('las flechas recorren las pestañas y dan la vuelta', () => {
    const tabs = ['analisis', 'que-paso', 'que-cambio'] as const
    expect(neighborTab(tabs, 'analisis', 1)).toBe('que-paso')
    expect(neighborTab(tabs, 'que-cambio', 1)).toBe('analisis')
    expect(neighborTab(tabs, 'analisis', -1)).toBe('que-cambio')
  })
})

describe('changesNote', () => {
  it('sin cambios dice por qué; con cambios, nada', () => {
    expect(changesNote(2, false, true)).toBeNull()
    expect(changesNote(0, true, false)).toBe('Qué cambió: se compara cuando todas las cuentas cierran el mes.')
    expect(changesNote(0, false, false)).toBe(
      'Qué cambió: hace falta al menos un mes completo anterior para comparar.',
    )
    expect(changesNote(0, false, true)).toBe('Qué cambió: todas las categorías están dentro de lo habitual.')
  })
})
