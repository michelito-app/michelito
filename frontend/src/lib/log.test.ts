import { describe, expect, it } from 'vitest'
import {
  affectedText,
  dayText,
  entryHref,
  entryLine,
  groupBySession,
  hintText,
  kindLabel,
  type LogEntry,
  logPath,
  NO_FILTERS,
  sessionLabel,
  undoNote,
} from './log'

function entry(patch: Partial<LogEntry> = {}): LogEntry {
  return {
    id: 1,
    at: '2026-02-20T18:40:00',
    author: 'usuario',
    kind: 'categoria',
    target_type: 'transaccion',
    target: 'a1b2c3d4e5f6a1b2c3d4e5f6',
    subject: 'RETIRO AHORRO LBRT',
    merchant: 'RETIRO AHORRO LBRT',
    before: { text: 'Efectivo', rows: {} },
    after: { text: 'Caja fuerte', rows: {} },
    affected: 1,
    fingerprints: ['a1b2c3d4e5f6a1b2c3d4e5f6'],
    reason: null,
    undoes: null,
    undone: false,
    can_undo: true,
    undo_message: '',
    blocked_by: null,
    fingerprint: 'a1b2c3d4e5f6a1b2c3d4e5f6',
    month: '2026-02',
    ...patch,
  }
}

const NOW = new Date(2026, 1, 20, 21, 0)

describe('entryLine', () => {
  it('se lee en una línea y marca un deshacer', () => {
    expect(entryLine(entry())).toBe('RETIRO AHORRO LBRT · Efectivo → Caja fuerte')
    expect(entryLine(entry({ undoes: 3 }))).toBe(
      'Deshecho: RETIRO AHORRO LBRT · Efectivo → Caja fuerte',
    )
  })
})

describe('sesiones', () => {
  it('hoy, ayer y días anteriores con el rango de horas', () => {
    expect(sessionLabel('2026-02-20T18:40:00', '2026-02-20T19:05:00', 14, NOW)).toBe(
      'Hoy, 18:40–19:05 · 14 cambios',
    )
    expect(sessionLabel('2026-02-19T09:00:00', '2026-02-19T09:00:00', 1, NOW)).toBe(
      'Ayer, 09:00 · 1 cambio',
    )
    expect(dayText(new Date(2025, 11, 3), NOW)).toMatch(/^3 dic 2025$/)
  })

  it('agrupa las entradas de la misma sesión', () => {
    const session = { session_start: '2026-02-20T18:40:00', session_end: '2026-02-20T19:05:00' }
    const groups = groupBySession(
      [
        entry({ id: 3, ...session, session_count: 2 }),
        entry({ id: 2, ...session, session_count: 2 }),
        entry({ id: 1, at: '2026-02-19T09:00:00' }),
      ],
      NOW,
    )
    expect(groups.map((g) => [g.label, g.entries.map((e) => e.id)])).toEqual([
      ['Hoy, 18:40–19:05 · 2 cambios', [3, 2]],
      ['Ayer, 09:00 · 1 cambio', [1]],
    ])
  })

  it('con filtros dice cuántos de la sesión se ven', () => {
    const session = { session_start: '2026-02-20T18:40:00', session_end: '2026-02-20T19:05:00' }
    const [group] = groupBySession([entry({ id: 3, ...session, session_count: 14 })], NOW)
    expect(group.label).toBe('Hoy, 18:40–19:05 · 1 de 14 cambios')
    expect(sessionLabel(session.session_start, session.session_end, 14, NOW, 2)).toBe(
      'Hoy, 18:40–19:05 · 2 de 14 cambios',
    )
  })
})

describe('enlaces y textos', () => {
  it('abre la transacción en su mes, o el comercio de una regla', () => {
    expect(entryHref(entry())).toBe('/transacciones?mes=2026-02&tx=a1b2c3d4e5f6a1b2c3d4e5f6')
    const rule = entry({ target_type: 'comercio', target: 'UBER EATS' })
    expect(entryHref(rule)).toBe('/transacciones?mes=2026-02&q=UBER+EATS')
    expect(entryHref(entry({ month: null }))).toBeNull()
    expect(entryHref(entry({ fingerprint: 'caja-7', month: '2026-01' }))).toBe(
      '/transacciones?mes=2026-01&tx=caja-7',
    )
  })

  it('arma la ruta de la API con los filtros', () => {
    expect(logPath(NO_FILTERS)).toBe('/api/log?limit=50')
    expect(logPath({ kind: 'nota', author: 'claude', q: ' uber ' }, 50, 100)).toBe(
      '/api/log?kind=nota&author=claude&q=uber&offset=50&limit=100',
    )
  })

  it('nombres de tipos, cuentas y pistas', () => {
    expect(kindLabel('regla')).toBe('Regla por comercio')
    expect(kindLabel('otro')).toBe('otro')
    expect([affectedText(1), affectedText(3)]).toEqual(['1 transacción', '3 transacciones'])
    const hint = { merchant: 'UBER EATS', category_id: 3, category: 'Delivery', count: 2 }
    expect(hintText(hint)).toBe('Las otras 2 veces lo pusiste en Delivery.')
  })

  it('explica por qué no hay deshacer', () => {
    expect(undoNote(entry())).toBe('')
    const message = 'Primero deshaz la entrada posterior n.º 4.'
    const blocked = entry({ can_undo: false, undo_message: message })
    expect(undoNote(blocked)).toContain('n.º 4')
  })
})
