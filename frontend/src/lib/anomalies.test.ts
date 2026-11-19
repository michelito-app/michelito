import { describe, expect, it } from 'vitest'
import {
  ATYPICAL_LEGEND,
  atypicalNote,
  contributionDetail,
  contributionDiff,
  contributionHref,
  deviationPercent,
  flagDeviation,
  flagMarks,
  flagSentence,
  flagText,
  hasAtypical,
  hasWhatHappened,
  monthFlags,
} from './anomalies'
import type { Contribution, MonthTotal } from './api'

function point(overrides: Partial<MonthTotal> = {}): MonthTotal {
  return {
    month: '2026-07',
    label: 'jul',
    total_cents: 4_000_000,
    income_cents: 0,
    partial: false,
    spent_flag: null,
    spent_habitual_cents: 1_000_000,
    income_flag: null,
    income_habitual_cents: 5_000_000,
    ...overrides,
  }
}

const AGENCY: Contribution = {
  side: 'gasto',
  merchant: 'AGENCIA FICTICIA',
  category: 'Viajes',
  amount_cents: 4_200_000,
  habitual_cents: 0,
  diff_cents: 4_200_000,
  count: 2,
  fingerprint: 'fp-1',
  day: '2026-07-06',
  description: 'AGENCIA FICTICIA VIAJES',
}

describe('marcas de mes atípico', () => {
  it('lista gasto e ingresos en ese orden', () => {
    const both = point({ spent_flag: 'up', income_flag: 'down' })
    expect(monthFlags(both)).toEqual([
      { side: 'gasto', direction: 'up' },
      { side: 'ingreso', direction: 'down' },
    ])
    expect(flagText(both)).toBe('gasto alto y ingresos bajos')
    expect(flagText(point())).toBeNull()
  })

  it('la nota nombra los meses atípicos', () => {
    const trend = [point({ month: '2026-06' }), point({ spent_flag: 'down' })]
    expect(atypicalNote(trend)).toBe('Meses atípicos: julio 2026 (gasto bajo)')
    expect(atypicalNote([point()])).toBeNull()
  })

  it('la frase compara con lo habitual', () => {
    expect(flagSentence(point({ spent_flag: 'up' }), { side: 'gasto', direction: 'up' })).toBe(
      'Gastos más altos que lo habitual: RD$ 40,000; lo habitual es RD$ 10,000',
    )
    expect(
      flagSentence(point({ income_flag: 'down' }), { side: 'ingreso', direction: 'down' }),
    ).toBe('Ingresos más bajos que lo habitual: RD$ 0; lo habitual es RD$ 50,000')
  })
})

describe('qué pasó', () => {
  it('detalle con monto, movimientos y lo habitual', () => {
    expect(contributionDiff(AGENCY)).toBe('+RD$ 42,000 frente a lo habitual')
    expect(contributionDetail(AGENCY)).toBe('Viajes · RD$ 42,000 en 2 movimientos · suele ser RD$ 0')
    expect(contributionDetail({ ...AGENCY, count: 1 })).toBe('Viajes · RD$ 42,000 · suele ser RD$ 0')
  })

  it('lo que no apareció lo dice', () => {
    const missing = { ...AGENCY, count: 0, amount_cents: 0, habitual_cents: 5_000_000, fingerprint: '' }
    expect(contributionDetail(missing)).toBe('Viajes · No apareció este mes (suele ser RD$ 50,000)')
  })

  it('enlaza la transacción, o busca el comercio si no apareció', () => {
    expect(contributionHref(AGENCY, '2026-07', ['b'])).toBe('/transacciones?mes=2026-07&tx=fp-1&cuentas=b')
    expect(contributionHref({ ...AGENCY, fingerprint: '' }, '2026-07', null)).toBe(
      '/transacciones?mes=2026-07&q=AGENCIA+FICTICIA',
    )
  })
})

describe('marcas sobre las barras', () => {
  it('cada lado lleva su flecha y sus palabras; lo malo va aparte', () => {
    expect(flagMarks(point({ spent_flag: 'up', income_flag: 'down' }))).toEqual([
      { side: 'gasto', direction: 'up', glyph: '▲', words: 'gasto alto', worse: true },
      { side: 'ingreso', direction: 'down', glyph: '▼', words: 'ingresos bajos', worse: true },
    ])
    expect(flagMarks(point({ spent_flag: 'down', income_flag: 'up' }))).toEqual([
      { side: 'gasto', direction: 'down', glyph: '▼', words: 'gasto bajo', worse: false },
      { side: 'ingreso', direction: 'up', glyph: '▲', words: 'ingresos altos', worse: false },
    ])
    expect(flagMarks(point())).toEqual([])
  })

  it('la leyenda sale de los umbrales', () => {
    expect(ATYPICAL_LEGEND).toBe('meses atípicos: se apartan más de 30% (y RD$ 10,000) de lo habitual')
  })

  it('el porcentaje lleva signo y se redondea; sin habitual no hay', () => {
    expect(deviationPercent(14_500, 10_000)).toBe('+45%')
    expect(deviationPercent(7_000, 10_000)).toBe('−30%')
    expect(deviationPercent(10_000, 10_000)).toBe('0%')
    expect(deviationPercent(10_000, null)).toBeNull()
    expect(deviationPercent(10_000, 0)).toBeNull()
  })

  it('la línea del tooltip dice el monto y cuánto se aparta', () => {
    const spent = point({ spent_flag: 'up' })
    expect(flagDeviation(spent, { side: 'gasto', direction: 'up' })).toBe(
      'Gasto RD$ 40,000 · +300% vs lo habitual',
    )
    const income = point({ income_cents: 2_500_000, income_flag: 'down' })
    expect(flagDeviation(income, { side: 'ingreso', direction: 'down' })).toBe(
      'Ingresos RD$ 25,000 · −50% vs lo habitual',
    )
    const unknown = point({ spent_flag: 'up', spent_habitual_cents: null })
    expect(flagDeviation(unknown, { side: 'gasto', direction: 'up' })).toBe('Gasto RD$ 40,000')
  })

  it('sabe si el gráfico tiene algún mes atípico', () => {
    expect(hasAtypical([point(), point({ income_flag: 'up' })])).toBe(true)
    expect(hasAtypical([point()])).toBe(false)
  })

  it('«Qué pasó» solo con un lado marcado que tenga comercios', () => {
    expect(hasWhatHappened(point({ spent_flag: 'up' }), [AGENCY])).toBe(true)
    expect(hasWhatHappened(point({ income_flag: 'up' }), [AGENCY])).toBe(false)
    expect(hasWhatHappened(point(), [AGENCY])).toBe(false)
    expect(hasWhatHappened(point({ spent_flag: 'up' }), [])).toBe(false)
    expect(hasWhatHappened(undefined, [AGENCY])).toBe(false)
  })
})
