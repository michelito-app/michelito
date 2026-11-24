import { describe, expect, it } from 'vitest'
import { dateRange } from './months'
import { t } from '@/i18n'
import { formatDop } from './money'
import { type TagCandidate, type TagMember, type TagTarget, canRemove, findTag, targetNote, visibleSelection, pickerSections, selectionSummary, spanLabel } from './tags'

function candidate(fingerprint: string, dop: number | null, counted = true): TagCandidate {
  return {
    fingerprint,
    day: '2026-05-16',
    merchant: 'SHOP',
    description: 'SHOP',
    category: 'Hogar y electrónica', // spanish-ui
    amount_cents: dop ?? 1000,
    currency: dop === null ? 'USD' : 'DOP',
    amount_dop_cents: dop,
    one_off: false,
    counted,
    likely: false,
    tagged: false,
  }
}

describe('spanLabel', () => {
  it('is empty for a tag with no members', () => {
    expect(spanLabel(null, null)).toBe('')
  })

  it('reads like any other date range', () => {
    expect(spanLabel('2026-04-18', '2026-07-07')).toBe(dateRange('2026-04-18', '2026-07-07'))
    expect(spanLabel('2025-12-18', '2026-01-09')).toBe(dateRange('2025-12-18', '2026-01-09'))
  })
})

describe('selectionSummary', () => {
  const rows = [candidate('a', 7000000), candidate('b', 4050000), candidate('c', null), candidate('d', 2400000, false)]

  it('counts every checked row and adds only what counts, in RD$', () => {
    expect(selectionSummary(rows, new Set(['a', 'b', 'c', 'd']))).toEqual({ count: 4, totalDopCents: 11050000 })
  })

  it('is zero with nothing checked', () => {
    expect(selectionSummary(rows, new Set())).toEqual({ count: 0, totalDopCents: 0 })
  })
})

describe('pickerSections', () => {
  it('puts the likely rows first and leaves the rest newest first', () => {
    const rows = [
      { ...candidate('a', 100), day: '2026-05-01' },
      { ...candidate('b', 200), day: '2026-05-03', likely: true },
      { ...candidate('c', 300), day: '2026-05-02' },
    ]
    const { likely, rest } = pickerSections(rows)
    expect(likely.map((r) => r.fingerprint)).toEqual(['b'])
    expect(rest.map((r) => r.fingerprint)).toEqual(['c', 'a'])
  })
})

describe('canRemove', () => {
  it('only lets a hand-tagged member be removed from the tag', () => {
    const manual: TagMember = { ...candidate('a', 100), derived: false, via: 'manual' }
    const fromGroup: TagMember = { ...manual, derived: true, via: 'group' }
    expect(canRemove(manual)).toBe(true)
    expect(canRemove(fromGroup)).toBe(false)
  })
})

describe('findTag', () => {
  const tags = [{ id: 1, name: 'Amueblar el apartamento' }, { id: 2, name: 'Viaje' }] // spanish-ui
  it('finds a tag by name ignoring case, accents and extra spaces', () => {
    expect(findTag(tags, '  VIÁJE ')?.id).toBe(2) // spanish-ui
  })
  it('is null for a new name', () => {
    expect(findTag(tags, 'Regalos')).toBeNull() // spanish-ui
  })
})

describe('targetNote', () => {
  const loan: TagTarget = { kind: 'loan', id: 3, name: 'Nevera', has_payout: false, still_to_pay_cents: 900000 } // spanish-ui
  it('says what is left for a financed loan', () => {
    expect(targetNote(loan)).toBe(t('tags.target.left', { amount: formatDop(900000) }))
  })
  it('explains why a loan whose money reached the account adds nothing', () => {
    expect(targetNote({ ...loan, has_payout: true, still_to_pay_cents: 0 })).toBe(t('tags.target.payout'))
  })
})

describe('visibleSelection', () => {
  it('keeps only the checked rows the filters still show, so the button tags what it counts', () => {
    const rows = [candidate('b', 200)]
    expect([...visibleSelection(new Set(['a', 'b']), rows)]).toEqual(['b'])
  })
})
