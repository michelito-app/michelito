import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { FLOW_COLORS, TONE_COLORS } from './colors'
import {
  BUILTIN,
  builtinName,
  canonicalCategory,
  CATEGORY_PALETTE,
  categoryColor,
  categoryGroups,
  choosable,
  colorFor,
  conflictText,
  countText,
  customColors,
  isLinkOnly,
  isNewCategoryOption,
  NEW_CATEGORY,
  NEW_CATEGORY_ACTION,
  NO_COLOR,
  parseKeywords,
  previewText,
  THIRD_PARTY,
} from './categories'

describe('categoryColor', () => {
  it('gives the design colours by spending rank and repeats when they run out', () => {
    expect(categoryColor(0)).toBe(CATEGORY_PALETTE[0])
    expect(categoryColor(10)).toBe(CATEGORY_PALETTE[0])
  })
})

describe('colorFor', () => {
  it("uses the category's rank in the month's Summary, as in its table", () => {
    const ranking = ['Groceries', 'Restaurants']
    expect(colorFor(ranking, 'Restaurants')).toBe(CATEGORY_PALETTE[1])
    expect(colorFor(ranking, 'Travel')).toBe(NO_COLOR)
  })
})

describe('categoryGroups', () => {
  const all = [
    { name: 'Groceries', kind: 'expense' },
    { name: 'Salary', kind: 'income' },
    { name: 'Restaurants', kind: 'expense' },
    { name: 'Between my accounts', kind: 'transfer' },
  ] as const
  const EXPENSES = t('categories.group.expense')
  const INCOME = t('categories.group.income')
  const TRANSFERS = t('categories.group.transfer')

  it('groups by kind in the order expenses, income, transfers', () => {
    expect([EXPENSES, INCOME, TRANSFERS]).toEqual(['Gastos', 'Ingresos', 'Transferencias']) // spanish-ui
    expect(categoryGroups(all)).toEqual([
      { label: EXPENSES, names: ['Groceries', 'Restaurants'] },
      { label: INCOME, names: ['Salary'] },
      { label: TRANSFERS, names: ['Between my accounts'] },
    ])
  })

  it('leaves out empty groups', () => {
    expect(categoryGroups(all.slice(0, 1))).toEqual([{ label: EXPENSES, names: ['Groceries'] }])
  })
})

describe('THIRD_PARTY', () => {
  it("is the server category's name and falls in the transfers group", () => {
    expect(THIRD_PARTY).toBe('Transferencias a terceros') // spanish-data: the server's seed name
    const groups = categoryGroups([
      { name: 'Loans', kind: 'expense' },
      { name: THIRD_PARTY, kind: 'transfer' },
    ])
    expect(groups).toEqual([
      { label: t('categories.group.expense'), names: ['Loans'] },
      { label: t('categories.group.transfer'), names: [THIRD_PARTY] },
    ])
  })
})

describe('canonicalCategory', () => {
  it('gives the current name of a renamed category, like `categories.canonical`', () => {
    expect(canonicalCategory('Efectivo y transferencias')).toBe('Efectivo') // spanish-data
    expect(canonicalCategory('Health')).toBe('Health')
  })
})

describe('editable categories', () => {
  it('categoryGroups leaves out hidden ones, except the one asked to keep', () => {
    const list = [
      { name: 'Groceries', kind: 'expense', hidden: false },
      { name: 'Old', kind: 'expense', hidden: true },
    ] as const
    const expenses = t('categories.group.expense')
    expect(categoryGroups(list)).toEqual([{ label: expenses, names: ['Groceries'] }])
    expect(categoryGroups(list, 'Old')).toEqual([{ label: expenses, names: ['Groceries', 'Old'] }])
  })

  it("builtinName gives today's name by the stable identity", () => {
    const list = [{ name: 'Remittances', builtin_key: 'THIRD_PARTY' }]
    expect(builtinName(list, BUILTIN.thirdParty, THIRD_PARTY)).toBe('Remittances')
    expect(builtinName([], BUILTIN.thirdParty, THIRD_PARTY)).toBe(THIRD_PARTY)
  })

  it('colorFor uses the picked colour before the rank', () => {
    const custom = customColors([
      { name: 'Travel', color: '#C2702E' },
      { name: 'Health', color: null },
    ])
    expect(custom).toEqual({ Travel: '#C2702E' })
    expect(colorFor(['Health'], 'Travel', custom)).toBe('#C2702E')
    expect(colorFor(['Health'], 'Health', custom)).toBe(CATEGORY_PALETTE[0])
  })

  it('the "new category" option cannot be the name of a category', () => {
    // The server strips spaces at the ends and collapses the inner ones: this value never comes
    // out of it.
    expect(NEW_CATEGORY).not.toBe(NEW_CATEGORY.trim().split(/\s+/).join(' '))
    expect(isNewCategoryOption({ dataset: { action: NEW_CATEGORY_ACTION } })).toBe(true)
    expect(isNewCategoryOption({ dataset: {} })).toBe(false)
    expect(isNewCategoryOption(undefined)).toBe(false)
  })

  it('parseKeywords splits on commas or lines and drops empty ones', () => {
    expect(parseKeywords(' garage, ,LAVADO DE AUTO\nGOMERA ')).toEqual([
      'garage',
      'LAVADO DE AUTO',
      'GOMERA',
    ])
  })

  it("texts of the preview and of the year's count", () => {
    expect(previewText(3, 'RD$ 1,250', null)).toBe(
      t('categories.preview.moves', { count: 3, money: 'RD$ 1,250' }),
    )
    expect(previewText(3, 'RD$ 1,250', null)).toBe('Esto moverá 3 transacciones (RD$ 1,250)') // spanish-ui
    expect(previewText(1, 'RD$ 0', 'US$ 25.00')).toBe(
      'Esto moverá 1 transacción (RD$ 0 y US$ 25.00 sin tasa)', // spanish-ui
    )
    expect(previewText(0, 'RD$ 0', null)).toBe(t('categories.preview.none'))
    expect(conflictText(0)).toBeNull()
    expect(conflictText(2)).toBe(t('categories.conflicts', { count: 2 }))
    expect(conflictText(2)).toMatch(/^2 transacciones coinciden también/) // spanish-ui
    expect(countText(1)).toBe('1 transacción este año') // spanish-ui
    expect(countText(12)).toBe(t('categories.countYear', { count: 12 }))
    expect(countText(0)).toBe('Sin transacciones este año') // spanish-ui
  })
})

describe('category palette', () => {
  // No category may be confused with the flow colours or with the former blue.
  const RESERVED = [
    ...Object.values(FLOW_COLORS).flatMap((c) => [c.strong, c.light]),
    ...Object.values(TONE_COLORS),
    '#5B7DB8', // the former income blue
    '#2F5FA8', // the former "less spending" blue
  ]

  function distance(a: string, b: string): number {
    const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    const [x, y] = [rgb(a), rgb(b)]
    return Math.hypot(...x.map((value, i) => value - y[i]))
  }

  it('avoids the income green, the terracotta, the third-party grey and the former blue', () => {
    for (const color of CATEGORY_PALETTE) {
      for (const reserved of RESERVED) {
        expect(distance(color.toUpperCase(), reserved.toUpperCase())).toBeGreaterThan(48)
      }
    }
  })

  it('has distinct colours', () => {
    expect(new Set(CATEGORY_PALETTE.map((c) => c.toUpperCase())).size).toBe(CATEGORY_PALETTE.length)
  })
})

describe('categories set only by their link', () => {
  it('are not picked by hand; investment returns are', () => {
    const items = [
      { name: 'Cash box', builtin_key: 'CASH_BOX' },
      { name: 'Investments', builtin_key: 'INVESTMENT' },
      { name: 'Capital returned', builtin_key: 'INVESTMENT_CAPITAL' },
      { name: 'Returns', builtin_key: 'INVESTMENT_RETURN' },
      { name: 'Mine', builtin_key: null },
    ]
    expect(choosable(items).map((c) => c.name)).toEqual(['Returns', 'Mine'])
    expect(isLinkOnly({ builtin_key: 'CASH_BOX' })).toBe(true)
    expect(isLinkOnly({ builtin_key: null })).toBe(false)
  })
})
