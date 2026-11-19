import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
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
    author: 'user',
    kind: 'category',
    target_type: 'transaction',
    target: 'a1b2c3d4e5f6a1b2c3d4e5f6',
    subject: 'RETIRO AHORRO LBRT',
    merchant: 'RETIRO AHORRO LBRT',
    before: { text: 'Cash', rows: {} },
    after: { text: 'Cash box', rows: {} },
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
  it('reads on one line and marks an undo', () => {
    const line = 'RETIRO AHORRO LBRT · Cash → Cash box'
    expect(entryLine(entry())).toBe(line)
    expect(entryLine(entry({ undoes: 3 }))).toBe(t('log.undone', { line }))
    expect(entryLine(entry({ undoes: 3 }))).toBe(`Deshecho: ${line}`) // spanish-ui
  })
})

describe('sessions', () => {
  it('today, yesterday and earlier days with the time span', () => {
    expect(sessionLabel('2026-02-20T18:40:00', '2026-02-20T19:05:00', 14, NOW)).toBe(
      'Hoy, 18:40–19:05 · 14 cambios', // spanish-ui
    )
    expect(sessionLabel('2026-02-19T09:00:00', '2026-02-19T09:00:00', 1, NOW)).toBe(
      t('log.session', {
        day: t('log.yesterday'),
        span: '09:00',
        changes: t('log.changes', { count: 1 }),
      }),
    )
    expect(dayText(new Date(2025, 11, 3), NOW)).toMatch(/^3 dic 2025$/)
  })

  it('groups the entries of the same session', () => {
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
      [sessionLabel(session.session_start, session.session_end, 2, NOW), [3, 2]],
      ['Ayer, 09:00 · 1 cambio', [1]], // spanish-ui
    ])
  })

  it("with filters says how many of the session's changes are shown", () => {
    const session = { session_start: '2026-02-20T18:40:00', session_end: '2026-02-20T19:05:00' }
    const [group] = groupBySession([entry({ id: 3, ...session, session_count: 14 })], NOW)
    expect(group.label).toBe('Hoy, 18:40–19:05 · 1 de 14 cambios') // spanish-ui
    expect(sessionLabel(session.session_start, session.session_end, 14, NOW, 2)).toBe(
      t('log.session', {
        day: t('log.today'),
        span: '18:40–19:05',
        changes: t('log.changesShown', { shown: 2, total: t('log.changes', { count: 14 }) }),
      }),
    )
  })
})

describe('links and texts', () => {
  it("opens the transaction in its month, or a rule's merchant", () => {
    expect(entryHref(entry())).toBe('/transactions?month=2026-02&tx=a1b2c3d4e5f6a1b2c3d4e5f6')
    const rule = entry({ target_type: 'merchant', target: 'UBER EATS' })
    expect(entryHref(rule)).toBe('/transactions?month=2026-02&q=UBER+EATS')
    expect(entryHref(entry({ month: null }))).toBeNull()
    expect(entryHref(entry({ fingerprint: 'cash-7', month: '2026-01' }))).toBe(
      '/transactions?month=2026-01&tx=cash-7',
    )
  })

  it('builds the API path with the filters', () => {
    expect(logPath(NO_FILTERS)).toBe('/api/log?limit=50')
    expect(logPath({ kind: 'note', author: 'claude', q: ' uber ' }, 50, 100)).toBe(
      '/api/log?kind=note&author=claude&q=uber&offset=50&limit=100',
    )
  })

  it('kind names, counts and hints', () => {
    expect(kindLabel('merchant_rule')).toBe(t('log.kind.merchant_rule'))
    expect(kindLabel('other')).toBe('other')
    expect([affectedText(1), affectedText(3)]).toEqual(['1 transacción', '3 transacciones']) // spanish-ui
    const hint = { merchant: 'UBER EATS', category_id: 3, category: 'Delivery', count: 2 }
    expect(hintText(hint)).toBe(t('log.hint', { count: 2, category: 'Delivery' }))
  })

  it('explains why there is no undo', () => {
    expect(undoNote(entry())).toBe('')
    const message = 'Undo the later entry no. 4 first.'
    const blocked = entry({ can_undo: false, undo_message: message })
    expect(undoNote(blocked)).toBe(message)
  })
})
