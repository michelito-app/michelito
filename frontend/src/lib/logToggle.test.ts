import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { entryHref, entryLine, linkLabel, type LogEntry, showsAffected, toggledText, undoNote } from './log'

function entry(patch: Partial<LogEntry> = {}): LogEntry {
  return {
    id: 7,
    at: '2026-02-20T18:40:00',
    author: 'user',
    kind: 'group_member',
    target_type: 'link',
    target: 'group-3',
    subject: 'Serie Mundial MLB',
    merchant: null,
    before: { text: 'Javier, en el grupo', rows: {} },
    after: { text: '—', rows: {} },
    affected: 0,
    fingerprints: [],
    reason: null,
    undoes: null,
    undone: false,
    can_undo: true,
    can_redo: false,
    undo_message: '',
    blocked_by: null,
    fingerprint: null,
    month: null,
    toggles: 0,
    summary: 'Quitaste a Javier del grupo Serie Mundial MLB',
    link_kind: 'group',
    link_id: 3,
    ...patch,
  }
}

describe('one row per change in the log', () => {
  it("reads Shared's sentence instead of before → after", () => {
    expect(entryLine(entry())).toBe('Quitaste a Javier del grupo Serie Mundial MLB')
    expect(entryLine(entry({ summary: null }))).toBe('Serie Mundial MLB · Javier, en el grupo → —')
  })

  it('links a group or a person, not a transaction, and drops "0 transactions"', () => {
    expect(entryHref(entry())).toBe('/shared/3')
    expect(linkLabel(entry())).toBe(t('log.row.viewGroup'))
    const person = entry({ target: 'contact-5', link_kind: 'contact', link_id: 5 })
    expect(entryHref(person)).toBe('/shared/people/5')
    expect(linkLabel(person)).toBe(t('log.row.viewPerson'))
    expect(entryHref(entry({ link_kind: null, link_id: null }))).toBeNull() // the group is gone
    expect(showsAffected(entry())).toBe(false)
    expect(showsAffected(entry({ affected: 1 }))).toBe(true)
    expect(showsAffected(entry({ target_type: 'transaction', affected: 0 }))).toBe(true)
  })

  it('says how many times it went back and forth, from two on', () => {
    expect(toggledText(entry({ toggles: 1 }))).toBeNull()
    expect(toggledText(entry({ toggles: 6 }))).toBe(t('log.row.toggled', { count: 6 }))
  })

  it('explains why the action that applies is blocked', () => {
    const undone = entry({ undone: true, can_undo: false, can_redo: true })
    expect(undoNote(undone)).toBe('')
    const blocked = entry({ undone: true, can_undo: false, can_redo: false, undo_message: 'n.º 9' })
    expect(undoNote(blocked)).toBe('n.º 9')
  })
})
