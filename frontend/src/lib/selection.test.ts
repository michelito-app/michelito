import { describe, expect, it } from 'vitest'
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
  category(1, 'Delivery', 'gasto'),
  category(2, 'Cripto', 'ingreso', { builtin_key: 'CRYPTO' }),
  category(3, 'Caja fuerte', 'transferencia', { builtin_key: 'CASH_BOX' }),
  category(4, 'Entre mis cuentas', 'transferencia'),
  category(5, 'Vieja', 'gasto', { hidden: true }),
]

describe('batchOptions', () => {
  it('solo créditos: todas menos las de vínculo y las ocultas', () => {
    const found = batchOptions(CATEGORIES, [{ amount_cents: -100 }])
    expect(found.categories.map((c) => c.name)).toEqual(['Delivery', 'Cripto', 'Entre mis cuentas'])
    expect(found.notice).toBeNull()
  })

  it('con débitos no ofrece ingresos; mezclados, lo avisa', () => {
    const debits = batchOptions(CATEGORIES, [{ amount_cents: 100 }])
    expect(debits.categories.map((c) => c.name)).toEqual(['Delivery', 'Entre mis cuentas'])
    expect(debits.notice).toBeNull()
    const mixed = batchOptions(CATEGORIES, [{ amount_cents: 100 }, { amount_cents: -100 }])
    expect(mixed.categories.map((c) => c.name)).toEqual(['Delivery', 'Entre mis cuentas'])
    expect(mixed.notice).toContain('débitos y créditos')
  })
})

describe('selección', () => {
  it('cuenta y suma sin signo; mezclados, lo que entra y lo que sale; sin tasa, aparte', () => {
    const credit = { amount_cents: -1_000_000, amount_dop_cents: -1_000_000 }
    const debit = { amount_cents: 500_000, amount_dop_cents: 500_000 }
    const usd = { amount_cents: 10_000, amount_dop_cents: null }
    expect(counterText([credit, credit])).toBe('2 seleccionadas · RD$ 20,000')
    expect(counterText([credit, debit])).toBe(
      '2 seleccionadas · entran RD$ 10,000 · salen RD$ 5,000',
    )
    expect(counterText([usd])).toBe('1 seleccionada · RD$ 0 · 1 sin tasa (no suma)')
    expect(counterText([debit, usd, usd])).toBe(
      '3 seleccionadas · RD$ 5,000 · 2 sin tasa (no suman)',
    )
  })

  it('suelta las que salen de la lista y no las devuelve', () => {
    const chosen = new Set(['a', 'b'])
    expect(pruned(chosen, [{ fingerprint: 'a' }, { fingerprint: 'b' }])).toBe(chosen)
    const narrowed = pruned(chosen, [{ fingerprint: 'a' }])
    expect([...narrowed]).toEqual(['a'])
    expect([...pruned(narrowed, [{ fingerprint: 'a' }, { fingerprint: 'b' }])]).toEqual(['a'])
  })

  it('lo visible: con grupos, solo los abiertos', () => {
    const groups = [
      { key: 'Salario', items: ['s1'] },
      { key: 'Otros ingresos', items: ['o1', 'o2'] },
    ]
    expect(visibleRows(groups, new Set(['Otros ingresos']))).toEqual(['o1', 'o2'])
    expect(visibleRows(groups, new Set())).toEqual([])
  })

  it('agrega, quita y suelta las que ya no se ven', () => {
    const once = toggled(new Set(), 'a')
    expect([...once]).toEqual(['a'])
    expect([...toggled(once, 'a')]).toEqual([])
    const items = [{ fingerprint: 'a' }, { fingerprint: 'b' }]
    expect(visibleChosen(items, new Set(['b', 'z']))).toEqual([{ fingerprint: 'b' }])
  })

  it('avisa las que fija un vínculo', () => {
    expect(fixedByLink({ link: 'exchange' })).toBe(true)
    expect(fixedByLink({ link: 'shared' })).toBe(false)
    expect(linkedText([{ link: '' }])).toBeNull()
    expect(linkedText([{ link: 'cash_box' }])).toContain('1 está en un vínculo')
    expect(linkedText([{ link: 'investment' }, { link: 'reimbursement' }])).toContain('2 están')
  })
})

describe('resultText', () => {
  const skip = (reason: BatchResult['skipped'][number]['reason']) => ({
    fingerprint: 'x',
    reason,
    message: '',
  })

  it('dice cuántas pasaron y por qué se omitieron las demás', () => {
    const result: BatchResult = {
      applied: Array.from({ length: 12 }, (_, i) => String(i)),
      skipped: [skip('vinculo'), skip('vinculo'), skip('vinculo'), skip('sin_cambio')],
      entry_id: 7,
    }
    expect(resultText(result, 'Cripto')).toBe(
      '12 pasaron a Cripto · 3 no se cambiaron: están en un vínculo · 1 no se cambió: ya estaba en esa categoría',
    )
    expect(resultText({ applied: ['a'], skipped: [], entry_id: 1 }, 'Cripto')).toBe('1 pasó a Cripto')
    expect(resultText({ applied: [], skipped: [skip('direccion')], entry_id: null }, 'Cripto')).toBe(
      'Ninguna cambió · 1 no se cambió: es un débito (no puede ser ingreso)',
    )
    const cash: BatchResult = { applied: [], skipped: [skip('caja')], entry_id: null }
    expect(resultText(cash, 'Cripto')).toContain('1 no se cambió: es de la caja fuerte')
  })
})
