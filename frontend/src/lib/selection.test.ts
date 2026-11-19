import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { formatDop } from './money'
import type { BatchResult, Category } from './api'
import {
  batchOptions,
  counterText,
  fixedByLink,
  linkedText,
  pruned,
  resultText,
  toggled,
  visibleChosen,
  visibleRows,
} from './selection'

function category(id: number, name: string, kind: Category['kind'], extra: Partial<Category> = {}): Category {
  return {
    id,
    name,
    kind,
    color: null,
    hidden: false,
    builtin: true,
    builtin_key: null,
    keywords: [],
    count_year: 0,
    ...extra,
  }
}

const CATEGORIES = [
  category(1, 'Delivery', 'expense'),
  category(2, 'Crypto', 'income', { builtin_key: 'CRYPTO' }),
  category(3, 'Cash box', 'transfer', { builtin_key: 'CASH_BOX' }),
  category(4, 'Between my accounts', 'transfer'),
  category(5, 'Old', 'expense', { hidden: true }),
]

describe('batchOptions', () => {
  it('credits only: all but the link ones and the hidden ones', () => {
    const found = batchOptions(CATEGORIES, [{ amount_cents: -100 }])
    expect(found.categories.map((c) => c.name)).toEqual(['Delivery', 'Crypto', 'Between my accounts'])
    expect(found.notice).toBeNull()
  })

  it('with debits it offers no income; mixed, it says so', () => {
    const debits = batchOptions(CATEGORIES, [{ amount_cents: 100 }])
    expect(debits.categories.map((c) => c.name)).toEqual(['Delivery', 'Between my accounts'])
    expect(debits.notice).toBeNull()
    const mixed = batchOptions(CATEGORIES, [{ amount_cents: 100 }, { amount_cents: -100 }])
    expect(mixed.categories.map((c) => c.name)).toEqual(['Delivery', 'Between my accounts'])
    expect(mixed.notice).toBe(t('common.selection.mixedNotice'))
  })
})

describe('selection', () => {
  it('counts and adds unsigned; mixed, what comes in and goes out; without a rate, apart', () => {
    const credit = { amount_cents: -1_000_000, amount_dop_cents: -1_000_000 }
    const debit = { amount_cents: 500_000, amount_dop_cents: 500_000 }
    const usd = { amount_cents: 10_000, amount_dop_cents: null }
    const count = (n: number) => t('common.selection.count', { count: n })
    const unrated = (n: number) => t('common.selection.unrated', { count: n })
    expect(counterText([credit, credit])).toBe(`${count(2)} · RD$ 20,000`)
    expect(counterText([credit, debit])).toBe(
      `${count(2)} · ${t('common.selection.inOut', { incoming: formatDop(1_000_000), outgoing: formatDop(500_000) })}`,
    )
    expect(counterText([usd])).toBe(`${count(1)} · RD$ 0 · ${unrated(1)}`)
    expect(counterText([debit, usd, usd])).toBe(`${count(3)} · RD$ 5,000 · ${unrated(2)}`)
    // The composed sentence, once, as it reads:
    expect(counterText([credit, debit])).toBe('2 seleccionadas · entran RD$ 10,000 · salen RD$ 5,000') // spanish-ui
    expect(counterText([debit, usd, usd])).toBe('3 seleccionadas · RD$ 5,000 · 2 sin tasa (no suman)') // spanish-ui
  })

  it('drops those that leave the list and does not bring them back', () => {
    const chosen = new Set(['a', 'b'])
    expect(pruned(chosen, [{ fingerprint: 'a' }, { fingerprint: 'b' }])).toBe(chosen)
    const narrowed = pruned(chosen, [{ fingerprint: 'a' }])
    expect([...narrowed]).toEqual(['a'])
    expect([...pruned(narrowed, [{ fingerprint: 'a' }, { fingerprint: 'b' }])]).toEqual(['a'])
  })

  it('what is visible: with groups, only the open ones', () => {
    const groups = [
      { key: 'Salary', items: ['s1'] },
      { key: 'Other income', items: ['o1', 'o2'] },
    ]
    expect(visibleRows(groups, new Set(['Other income']))).toEqual(['o1', 'o2'])
    expect(visibleRows(groups, new Set())).toEqual([])
  })

  it('adds, removes and drops those no longer shown', () => {
    const once = toggled(new Set(), 'a')
    expect([...once]).toEqual(['a'])
    expect([...toggled(once, 'a')]).toEqual([])
    const items = [{ fingerprint: 'a' }, { fingerprint: 'b' }]
    expect(visibleChosen(items, new Set(['b', 'z']))).toEqual([{ fingerprint: 'b' }])
  })

  it('warns about those a link fixes', () => {
    expect(fixedByLink({ link: 'exchange' })).toBe(true)
    expect(fixedByLink({ link: 'shared' })).toBe(false)
    expect(linkedText([{ link: '' }])).toBeNull()
    expect(linkedText([{ link: 'cash_box' }])).toBe(t('common.selection.linked', { count: 1 }))
    expect(linkedText([{ link: 'investment' }, { link: 'reimbursement' }])).toBe(
      t('common.selection.linked', { count: 2 }),
    )
  })
})

describe('resultText', () => {
  const skip = (reason: BatchResult['skipped'][number]['reason']) => ({
    fingerprint: 'x',
    reason,
    message: '',
  })

  it('says how many moved and why the others were skipped', () => {
    const result: BatchResult = {
      applied: Array.from({ length: 12 }, (_, i) => String(i)),
      skipped: [skip('linked'), skip('linked'), skip('linked'), skip('unchanged')],
      entry_id: 7,
    }
    expect(resultText(result, 'Crypto')).toBe(
      [
        t('common.selection.applied', { count: 12, category: 'Crypto' }),
        t('common.selection.skipped.linked', { count: 3 }),
        t('common.selection.skipped.unchanged', { count: 1 }),
      ].join(' · '),
    )
    expect(resultText(result, 'Cripto')).toBe(
      '12 pasaron a Cripto · 3 no se cambiaron: están en un vínculo · 1 no se cambió: ya estaba en esa categoría', // spanish-ui
    )
    expect(resultText({ applied: ['a'], skipped: [], entry_id: 1 }, 'Crypto')).toBe(
      t('common.selection.applied', { count: 1, category: 'Crypto' }),
    )
    expect(resultText({ applied: [], skipped: [skip('direction')], entry_id: null }, 'Crypto')).toBe(
      'Ninguna cambió · 1 no se cambió: es un débito (no puede ser ingreso)', // spanish-ui
    )
    const cash: BatchResult = { applied: [], skipped: [skip('cash_box')], entry_id: null }
    expect(resultText(cash, 'Crypto')).toBe(
      [
        t('common.selection.applied', { count: 0, category: 'Crypto' }),
        t('common.selection.skipped.cashBox', { count: 1 }),
      ].join(' · '),
    )
  })
})
