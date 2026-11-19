import { describe, expect, it } from 'vitest'
import type { Insight, MonthOption } from './api'
import {
  analyzeCommand,
  canSave,
  insightPath,
  markdownBlocks,
  monthsWithout,
  remaining,
  savedText,
  TEXT_MAX,
} from './insights'

const INSIGHT: Insight = {
  month: '2026-02',
  label: 'Febrero 2026',
  text: 'Viaje grande.',
  accounts: null,
  created_at: '2026-03-02T10:00:00+00:00',
  updated_at: '2026-03-02T10:00:00+00:00',
  stale: false,
}

const MONTHS: MonthOption[] = [
  { month: '2026-02', label: 'Febrero 2026', partial: true },
  { month: '2026-01', label: 'Enero 2026', partial: false },
]

describe('análisis guardados', () => {
  it('el comando para analizar un mes', () => {
    expect(analyzeCommand('2026-01')).toBe('finanzas analisis 2026-01')
  })

  it('los meses sin análisis, en el orden de la API', () => {
    expect(monthsWithout([INSIGHT], MONTHS).map((m) => m.month)).toEqual(['2026-01'])
    expect(monthsWithout([], MONTHS)).toHaveLength(2)
  })

  it('cuándo se guardó o se editó', () => {
    expect(savedText(INSIGHT)).toBe('Guardado el 2 de marzo de 2026')
    expect(savedText({ ...INSIGHT, updated_at: '2026-03-05T09:00:00+00:00' })).toBe(
      'Editado el 5 de marzo de 2026',
    )
  })

  it('límite de 4000 caracteres sin contar espacios de los bordes', () => {
    expect(remaining('  hola  ')).toBe(TEXT_MAX - 4)
    expect(canSave('   ')).toBe(false)
    expect(canSave('x'.repeat(TEXT_MAX))).toBe(true)
    expect(canSave('x'.repeat(TEXT_MAX + 1))).toBe(false)
  })

  it('Markdown sencillo a bloques de texto (sin HTML)', () => {
    const text = '## Febrero\n\nGasté **más** de lo\nhabitual.\n\n- Viaje `grande`\n- Streaming\n1. Uno\n<b>x</b>'
    expect(markdownBlocks(text)).toEqual([
      { kind: 'heading', text: 'Febrero' },
      { kind: 'paragraph', text: 'Gasté más de lo habitual.' },
      { kind: 'list', items: ['Viaje grande', 'Streaming', 'Uno'] },
      { kind: 'paragraph', text: '<b>x</b>' },
    ])
    expect(markdownBlocks('   ')).toEqual([])
  })

  it('ruta de la API', () => {
    expect(insightPath('2026-02')).toBe('/api/insights/2026-02')
  })
})
